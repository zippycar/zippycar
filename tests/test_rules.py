"""The rules about removed and retired features: the data file, versions, and every rule in action."""

import re
from datetime import date
from pathlib import Path

import pytest
import yaml

from ha_config_doctor.catalog import ERROR, TIDY, WARNING
from ha_config_doctor.cli import main
from ha_config_doctor.doctor import examine
from ha_config_doctor.report import render_html, render_markdown
from ha_config_doctor.rules import (
    BASIS, KINDS, RulesProblem, fix_for, judge, legacy_template_replacement, load_rules, parse_version,
)

from .conftest import REPO, SAMPLES, automation_config, codes, findings_for, reg_entity, registry

BOOK = load_rules()
RULES_FILE = REPO / "data" / "ha_rules.yaml"


def by_rule(result, rule_id):
    return [f for f in result.findings.items if f.rule_id == rule_id]


# ------------------------------------------------------------------ the data file

def test_rules_file_is_complete_and_well_formed():
    raw = yaml.safe_load(RULES_FILE.read_text(encoding="utf-8"))
    assert raw["schema"] == 1 and parse_version(raw["newest_release_known"])
    assert len(BOOK.rules) == len(raw["rules"]) >= 30
    for rule in BOOK.rules:
        assert rule.kind in KINDS and rule.basis in BASIS
        assert rule.verification in ("verified", "unverified")
        assert rule.source.startswith("https://www.home-assistant.io/"), rule.id
        date.fromisoformat(rule.as_of)
        assert rule.deprecated_in or rule.removed_in or rule.changed_in or rule.planned_removal
        for field in ("deprecated_in", "removed_in", "changed_in", "planned_removal"):
            assert field in next(r for r in raw["rules"] if r["id"] == rule.id) or field in ("changed_in", "planned_removal") \
                or rule.kind == "changed", f"{rule.id} should record {field} (null if not known)"


def test_rules_are_written_in_plain_english():
    jargon = re.compile(r"\b(deprecat\w*|regex|schema|boolean|null|parse[rd]?|exception)\b", re.I)
    for rule in BOOK.rules:
        for text in (rule.explanation, rule.fix):
            assert not jargon.search(text), (rule.id, text)
            assert text.rstrip()[-1] in '.)"', (rule.id, text)


def test_nothing_could_be_verified_so_every_rule_says_so():
    # home-assistant.io could not be reached when these rules were written (see the README).
    assert all(rule.verification == "unverified" for rule in BOOK.rules)
    assert "could not be reached" in BOOK.verification_status


def test_owner_supplied_facts_are_recorded():
    legacy = BOOK.by_id("legacy-template-entities")
    assert (legacy.deprecated_in, legacy.removed_in, legacy.basis) == ("2025.12", "2026.6", "owner")
    assert set(legacy.match["domains"]) == {"alarm_control_panel", "binary_sensor", "cover", "fan", "light", "lock",
                                            "sensor", "switch", "vacuum", "weather"}
    see = BOOK.by_id("device-tracker-see")
    assert see.deprecated_in and see.basis == "owner"
    for rule_id, action in (("mqtt-publish-needs-admin", "mqtt.publish"), ("synology-reboot-needs-admin", "synology_dsm.reboot")):
        rule = BOOK.by_id(rule_id)
        assert rule.changed_in == "2026.10" and action in rule.match["actions"] and rule.basis == "owner"
    assert any(item["id"] == "yaml-trigger-ids" for item in BOOK.still_supported)


def test_no_retirement_facts_are_written_into_the_program():
    generic = {"host", "port", "ssl", "map", "mqtt", "ping", "version", "template", "light.turn_on", "light.toggle",
               "password", "username", "protocol", "discovery", "certificate", "client_id", "keepalive", "broker",
               "uptime", "season", "moon", "workday", "time_date", "command_line"}
    names = set()
    for rule in BOOK.rules:
        for key in ("names", "actions", "options", "data", "platforms", "attributes"):
            names |= {str(x) for x in rule.match.get(key) or []}
    source = "\n".join(p.read_text(encoding="utf-8") for p in (REPO / "src").rglob("*.py"))
    for name in sorted(names - generic):
        assert not re.search(r"""["']""" + re.escape(name) + r"""["']""", source), f"{name} is written into the code"


def test_rules_file_problems_are_explained(tmp_path):
    bad = tmp_path / "rules.yaml"
    bad.write_text("schema: 1\nnewest_release_known: '2026.10'\nrules:\n  - id: x\n    kind: action\n    match: {actions: [a.b]}\n"
                   "    removed_in: soon\n    explanation: E.\n    fix: F.\n    source: https://www.home-assistant.io/\n"
                   "    as_of: '2026-10-28'\n    verification: unverified\n    basis: owner\n", encoding="utf-8")
    with pytest.raises(RulesProblem, match="isn't a version"):
        load_rules(bad)
    with pytest.raises(RulesProblem):
        load_rules(tmp_path / "missing.yaml")


# ------------------------------------------------------------------ versions and severities

@pytest.mark.parametrize("text,parts", [
    ("2026.10.4", (2026, 10, 4)), ("2026.6", (2026, 6, 0)), ("2026.11.0b2", (2026, 11, 0)),
    ("2026.11.0.dev20261020", (2026, 11, 0)), (" 2025.12.1\n", (2025, 12, 1)), ("nonsense", None), ("2026.13", None),
])
def test_versions(text, parts):
    assert parse_version(text) == parts


def test_severity_depends_on_the_version():
    legacy = BOOK.by_id("legacy-template-entities")
    assert judge(legacy, (2026, 10, 4)).severity == ERROR
    assert judge(legacy, (2026, 6, 0)).severity == ERROR
    assert judge(legacy, (2026, 5, 3)).severity == WARNING
    assert judge(legacy, (2025, 11, 0)).severity == TIDY
    see = BOOK.by_id("device-tracker-see")
    assert judge(see, (2026, 10, 4)).severity == WARNING and "2027.5" in judge(see, (2026, 10, 4)).when
    assert judge(see, (2026, 4, 0)).severity == TIDY
    assert "arrive in Home Assistant 2026.6" in fix_for(see, (2026, 5, 0)) and "template device tracker" in fix_for(see, (2026, 10, 0))
    admin = BOOK.by_id("mqtt-publish-needs-admin")
    assert judge(admin, (2026, 10, 0)).severity == WARNING
    assert judge(admin, (2026, 9, 2)).severity == TIDY


def test_version_comes_from_the_folder_or_the_option(make_config):
    root = make_config({"configuration.yaml": "x: 1\n", ".HA_VERSION": "2026.4.1\n"})
    assert examine(root).version.text == "2026.4.1"
    assert examine(root).version.source == "file"
    assert examine(root, ha_version="2026.10.4").version.parts == (2026, 10, 4)
    (root / ".HA_VERSION").unlink()
    assumed = examine(root).version
    assert assumed.source == "assumed" and assumed.parts[:2] == BOOK.newest_release_known[:2]
    assert examine(root, ha_version="2027.3").version.newer_than_rules
    with pytest.raises(RulesProblem):
        examine(root, ha_version="next year")


def test_report_says_which_version_and_how_sure_the_rules_are():
    result = examine(SAMPLES / "faulty-config")
    html, md = render_html(result), render_markdown(result)
    for text in (html, md):
        assert "2026.10.4 (from the .HA_VERSION file in the folder)" in text
        assert "not yet been checked against the official release notes" in text
        assert "https://www.home-assistant.io/blog/2026/06/03/release-20266/" in text
        assert "default_entity_id: sensor.outside_feels_like" in text
    assert '<span class="badge w">unverified</span>' in html


# ------------------------------------------------------------------ every rule, in action

def _config_for(rule) -> tuple[dict, str]:
    """A small configuration that should set off this rule, and the place it should be reported."""

    m = rule.match
    first = lambda key: str((m.get(key) or [""])[0])  # noqa: E731
    files = automation_config("[]\n")
    if rule.kind == "integration":
        files["configuration.yaml"] += f"{first('names')}:\n  some_setting: 1\n"
    elif rule.kind == "platform":
        domain = first("domains") or "sensor"
        files["configuration.yaml"] += f"{domain}:\n  - platform: {first('platforms')}\n    name: Example\n"
    elif rule.kind == "legacy_template":
        domain = first("domains")
        plural = BOOK.conversion["plural_keys"].get(domain)
        body = f"    {plural}:\n      example:\n        value_template: \"{{{{ true }}}}\"\n" if plural else "    name: Example\n"
        files["configuration.yaml"] += f"{domain}:\n  - platform: template\n{body}"
    elif rule.kind == "option":
        files["configuration.yaml"] += f"{m['section']}:\n  {first('options')}: x\n"
    elif rule.kind == "platform_option":
        files["configuration.yaml"] += f"sensor:\n  - platform: history_stats\n    name: Example\n    {first('options')}: x\n"
    elif rule.kind == "automation_option":
        files["automations.yaml"] = f"- id: a\n  alias: A\n  {first('options')}: true\n  triggers: []\n  actions: []\n"
    elif rule.kind in ("action", "action_data"):
        data = f"\n    data:\n      {first('data')}: 1" if rule.kind == "action_data" else ""
        files["automations.yaml"] = f"- id: a\n  alias: A\n  triggers: []\n  actions:\n  - action: {first('actions')}{data}\n"
    elif rule.kind == "changed":
        files["scripts.yaml"] = f"example:\n  sequence:\n    - action: {first('actions')}\n"
    elif rule.kind == "template_attribute":
        entity = f"{first('domains')}.home"
        files["automations.yaml"] = (f"- id: a\n  alias: A\n  triggers: []\n  actions:\n  - action: notify.notify\n"
                                     f"    data:\n      message: \"{{{{ state_attr('{entity}', '{first('attributes')}') }}}}\"\n")
    return files, rule.kind


@pytest.mark.parametrize("rule", BOOK.rules, ids=[r.id for r in BOOK.rules])
def test_every_rule_finds_what_it_describes(run, rule):
    files, _ = _config_for(rule)
    files[".HA_VERSION"] = "2026.10.4\n"
    found = by_rule(run(files), rule.id)
    assert found, f"rule {rule.id} found nothing"
    assert {f.severity for f in found} == {judge(rule, (2026, 10, 4)).severity}
    assert all(f.source == rule.source and f.when and f.provenance for f in found)


def test_behaviour_changes_only_where_they_matter(run):
    files = automation_config("- id: a\n  alias: A\n  triggers: []\n  actions:\n  - action: mqtt.publish\n    data:\n      topic: x\n")
    assert not by_rule(run(files), "mqtt-publish-needs-admin")  # automations that start by themselves are fine
    files["scripts.yaml"] = "say:\n  sequence:\n    - action: mqtt.publish\n      data:\n        topic: x\n"
    assert by_rule(run(files), "mqtt-publish-needs-admin")


# ------------------------------------------------------------------ old template entities

LEGACY = {
    "sensor:\n  - platform: template\n    sensors:\n      feels_like:\n        friendly_name: Feels like\n"
    "        unique_id: feels_like_1\n        unit_of_measurement: °C\n        value_template: \"{{ 1 }}\"\n"
    "        icon_template: \"{{ 'mdi:thermometer' }}\"\n        availability_template: \"{{ true }}\"\n"
    "        entity_id: sensor.outside\n": None,
}


def test_legacy_template_replacement_uses_the_modern_names():
    data = yaml.safe_load(next(iter(LEGACY)))["sensor"][0]
    text = legacy_template_replacement("sensor", data, BOOK.conversion)
    modern = yaml.safe_load(text)["template"][0]["sensor"][0]
    assert modern == {
        "name": "Feels like", "unique_id": "feels_like_1", "default_entity_id": "sensor.feels_like", "state": "{{ 1 }}",
        "unit_of_measurement": "°C", "icon": "{{ 'mdi:thermometer' }}", "availability": "{{ true }}",
    }
    assert text.startswith("# Suggested replacement")


def test_legacy_templates_are_errors_on_2026_10_and_their_entities_are_gone(run):
    files = automation_config(
        "- id: a\n  alias: Uses it\n  triggers:\n  - trigger: numeric_state\n    entity_id: sensor.feels_like\n    below: 0\n"
        "  actions:\n  - action: notify.notify\n    data:\n      message: \"{{ states('sensor.feels_like') }}\"\n",
        {".storage/core.entity_registry": registry([reg_entity("sensor.feels_like", platform="template")]),
         ".HA_VERSION": "2026.10.4\n"})
    files["configuration.yaml"] += next(iter(LEGACY))
    result = run(files)
    legacy = findings_for(result, "legacy-template-entity")[0]
    assert legacy.severity == ERROR and "Removed in Home Assistant 2026.6" in legacy.when
    assert "default_entity_id: sensor.feels_like" in legacy.example
    gone = [f for f in result.findings.items if f.code == "unknown-entity" and "sensor.feels_like" in f.detail]
    assert gone and "2026.6" in gone[0].detail and gone[0].severity == ERROR
    assert any(f.code == "template-missing-entity" and "sensor.feels_like" in f.detail for f in result.findings.items)

    files[".HA_VERSION"] = "2026.5.2\n"
    earlier = run(files)
    assert findings_for(earlier, "legacy-template-entity")[0].severity == WARNING
    assert not [f for f in earlier.findings.items if f.code == "unknown-entity" and "feels_like" in f.detail]


def test_template_device_trackers_are_understood(run):
    files = automation_config(
        "- id: a\n  alias: A\n  triggers:\n  - trigger: state\n    entity_id: device_tracker.example_phone\n    to: home\n"
        "    from: not_home\n  actions: []\n", {".storage/core.entity_registry": registry([]), ".HA_VERSION": "2026.10.4\n"})
    files["configuration.yaml"] += ("template:\n  - device_tracker:\n      - name: Example phone\n"
                                    "        latitude: \"{{ 0 }}\"\n        longitude: \"{{ 0 }}\"\n")
    assert "unknown-entity" not in codes(run(files))


# ------------------------------------------------------------------ still supported

def test_yaml_trigger_ids_are_never_reported(run):
    text = ("- id: a\n  alias: Uses trigger ids\n  triggers:\n  - trigger: state\n    entity_id: binary_sensor.door\n"
            "    from: \"off\"\n    to: \"on\"\n    id: opened\n  - trigger: state\n    entity_id: binary_sensor.door\n"
            "    from: \"on\"\n    to: \"off\"\n    id: closed\n  actions:\n  - choose:\n    - conditions:\n"
            "      - condition: trigger\n        id: opened\n      sequence: []\n    - conditions:\n"
            "      - condition: trigger\n        id: [closed]\n      sequence: []\n")
    result = run(automation_config(text, {".HA_VERSION": "2026.10.4\n"}))
    assert not [f for f in result.findings.items if f.rule_id or f.code in ("unknown-trigger-id", "unknown-automation-key")]


# ------------------------------------------------------------------ command line

def test_ha_version_option_and_list_rules(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["check", str(SAMPLES / "healthy-config"), "--ha-version", "2026.10.4"]) == 0
    assert "Checked against Home Assistant 2026.10.4." in capsys.readouterr().out
    assert main(["check", str(SAMPLES / "healthy-config"), "--ha-version", "soon"]) == 2
    assert main(["list-rules", "--ha-version", "2026.5"]) == 0
    out = capsys.readouterr().out
    assert "[Warning] legacy-template-entities (unverified, from owner)" in out
    custom = tmp_path / "rules.yaml"
    custom.write_text(RULES_FILE.read_text(encoding="utf-8"), encoding="utf-8")
    assert main(["check", str(SAMPLES / "healthy-config"), "--rules", str(custom)]) == 0


def test_installed_rules_file_is_the_one_in_data(tmp_path):
    assert Path(BOOK.path).name == "ha_rules.yaml"
    assert Path(BOOK.path).read_text(encoding="utf-8") == RULES_FILE.read_text(encoding="utf-8")
