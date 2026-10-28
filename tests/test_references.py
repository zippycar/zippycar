"""Cross-checking entity names against Home Assistant's own records, read-only."""

import builtins
import io
from pathlib import Path

from ha_config_doctor.registry import NEVER_OPENED, Registry

from .conftest import automation_config, codes, findings_for, reg_entity, registry


def _uses(*entities: str, extra_steps: str = "") -> str:
    steps = "".join(f"    - action: homeassistant.turn_on\n      target:\n        entity_id: {e}\n" for e in entities)
    return f"- id: a\n  alias: Uses things\n  triggers: []\n  actions:\n{steps}{extra_steps}"


def test_disabled_deleted_orphaned_and_missing(run):
    storage = {
        ".storage/core.entity_registry": registry(
            [reg_entity("light.ok", device_id="dev1"), reg_entity("light.off", disabled_by="user"),
             reg_entity("light.lost_device", device_id="gone"), reg_entity("light.parked", device_id="dev2")],
            deleted=[{"entity_id": "light.removed", "orphaned_timestamp": None, "id": "x1"},
                     {"entity_id": "light.orphan", "orphaned_timestamp": 1700000000.0, "id": "x2"}]),
        ".storage/core.device_registry": {"data": {"devices": [{"id": "dev1", "disabled_by": None},
                                                               {"id": "dev2", "disabled_by": "user"}],
                                                   "deleted_devices": [{"id": "gone"}]}},
    }
    result = run(automation_config(_uses("light.ok", "light.off", "light.removed", "light.orphan",
                                         "light.lost_device", "light.parked", "light.typo_kitchen"), storage))
    found = {(f.code, f.detail.split(" ")[0]) for f in result.findings.items}
    assert ("disabled-entity", "light.off") in found
    assert ("deleted-entity", "light.removed") in found
    assert ("orphaned-entity", "light.orphan") in found
    assert ("orphaned-entity", "light.lost_device") in found
    assert any(f.code == "disabled-entity" and "device" in f.detail for f in result.findings.items)
    assert ("unknown-entity", "There") in found
    assert not any("light.ok" in f.detail for f in result.findings.items)


def test_did_you_mean(run):
    storage = {".storage/core.entity_registry": registry([reg_entity("light.kitchen_ceiling")])}
    result = run(automation_config(_uses("light.kitchen_celing"), storage))
    assert 'Did you mean "light.kitchen_ceiling"' in findings_for(result, "unknown-entity")[0].detail


def test_trigger_on_disabled_entity_says_it_can_never_fire(run):
    storage = {".storage/core.entity_registry": registry([reg_entity("binary_sensor.door", disabled_by="integration")])}
    text = "- id: a\n  alias: A\n  triggers:\n    - trigger: state\n      entity_id: binary_sensor.door\n      to: \"on\"\n  actions: []\n"
    finding = findings_for(run(automation_config(text, storage)), "disabled-entity")[0]
    assert "never be started" in finding.detail


def test_dead_scripts_scenes_helpers_services(run):
    steps = ("    - action: script.missing_one\n    - action: shell_command.not_there\n"
             "    - scene: scene.nope\n    - action: input_boolean.turn_on\n      target:\n        entity_id: input_boolean.nope\n"
             "    - action: automation.trigger\n      target:\n        entity_id: automation.nope\n")
    storage = {".storage/core.entity_registry": registry([])}
    result = run(automation_config(_uses(extra_steps=steps), storage))
    assert {"missing-script", "missing-service", "missing-scene", "missing-helper", "missing-automation"} <= codes(result)


def test_yaml_defined_things_count_as_existing(run):
    files = automation_config(_uses("input_boolean.guest", "script.night", "group.downstairs", "sensor.legacy_one",
                                    "zone.home", "sensor.from_template", "scene.evening"),
                              {".storage/core.entity_registry": registry([])})
    files["configuration.yaml"] += (
        "input_boolean:\n  guest:\n    name: Guest\n"
        "group:\n  downstairs:\n    entities: [input_boolean.guest]\n"
        "sensor:\n  - platform: template\n    sensors:\n      legacy_one:\n        value_template: \"{{ 1 }}\"\n"
        "template:\n  - sensor:\n      - name: From template\n        state: \"{{ 1 }}\"\n"
        "scene:\n  - name: Evening\n    entities:\n      input_boolean.guest: \"on\"\n")
    files["scripts.yaml"] = "night:\n  sequence:\n    - action: input_boolean.turn_off\n      target:\n        entity_id: input_boolean.guest\n"
    result = run(files)
    assert not {"unknown-entity", "missing-helper", "missing-script", "missing-scene"} & codes(result)


def test_restore_state_confirms_entities_not_in_the_registry(run):
    storage = {".storage/core.entity_registry": registry([]),
               ".storage/core.restore_state": {"data": [{"state": {"entity_id": "sensor.remembered", "state": "4",
                                                                    "attributes": {"access_token": "do-not-keep-me"}}}]}}
    result = run(automation_config(_uses("sensor.remembered"), storage))
    assert "unknown-entity" not in codes(result)
    assert result.registry.restore == {"sensor.remembered": "4"}  # attributes are dropped


def test_without_storage_only_certain_things_are_reported(run):
    result = run(automation_config(_uses("light.anything", "input_boolean.maybe_ui", extra_steps="    - action: script.nope\n")))
    assert "unknown-entity" not in codes(result)
    assert findings_for(result, "missing-helper")[0].severity == "Warning"
    assert findings_for(result, "missing-script")[0].severity == "Error"


def test_device_and_registry_id_references(run):
    storage = {".storage/core.entity_registry": registry([reg_entity("light.hall", registry_id="a" * 32)]),
               ".storage/core.device_registry": {"data": {"devices": [{"id": "dev1"}], "deleted_devices": []}}}
    steps = ("    - device_id: dev1\n      domain: light\n      entity_id: " + "a" * 32 + "\n      type: turn_on\n"
             "    - device_id: dev_missing\n      domain: light\n      entity_id: " + "b" * 32 + "\n      type: turn_on\n")
    result = run(automation_config(_uses(extra_steps=steps), storage))
    assert len(findings_for(result, "unknown-device")) == 1
    assert len(findings_for(result, "unknown-entity")) == 1


def test_unused_helpers_consider_dashboards(run):
    files = automation_config(_uses("input_boolean.used"), {
        ".storage/core.entity_registry": registry([reg_entity("input_boolean.ui_only", platform="input_boolean")]),
        ".storage/lovelace": {"data": {"config": {"views": [{"cards": [{"entity": "input_boolean.on_dashboard"}]}]}}},
    })
    files["configuration.yaml"] += "input_boolean:\n  used: {}\n  on_dashboard: {}\n  forgotten: {}\n"
    unused = {f.detail.split(" ")[0] for f in findings_for(run(files), "unused-helper")}
    assert unused == {"input_boolean.forgotten", "input_boolean.ui_only"}


def test_files_with_logins_are_never_opened(make_config, monkeypatch):
    root = make_config({"configuration.yaml": "x: 1\n", ".storage/core.entity_registry": registry([]),
                        **{f".storage/{name}": {"data": {"token": "should-never-be-read"}} for name in NEVER_OPENED}})
    opened: list[str] = []
    real_open = Path.open

    def spy(self, *args, **kwargs):
        opened.append(self.name)
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", spy)
    real_builtin_open = builtins.open

    def spy_builtin(file, *args, **kwargs):
        opened.append(Path(str(file)).name)
        return real_builtin_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy_builtin)
    monkeypatch.setattr(io, "open", spy_builtin)
    Registry(root)
    assert "core.entity_registry" in opened
    assert not set(opened) & set(NEVER_OPENED)
