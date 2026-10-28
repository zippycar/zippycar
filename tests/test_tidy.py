"""Tidy mode: corrected copies only, provably the same meaning, comments kept, originals untouched."""

import pytest

from ha_config_doctor.doctor import examine
from ha_config_doctor.report import write_change_log
from ha_config_doctor.tidy import (
    MARKER, OutputFolderProblem, Targets, check_output_folder, comment_texts, same_meaning, tidy, tidy_text,
)
from ha_config_doctor.yamlio import parse_yaml, to_plain

from .conftest import folder_fingerprint

OLD_STYLE = """\
# My automations
- alias: Hall light
  id: hall_light
  mode: restart
  trigger:
  - platform: state
    entity_id: binary_sensor.hall_motion
    to: 'on'
  action:
  - service: light.turn_on
    data_template:
      entity_id: light.hall
  - wait_for_trigger:
    - platform: state
      entity_id: binary_sensor.hall_motion
      to: 'off'
    timeout: 60
- id: second
  alias: Second
  description: ""
  triggers: []
  actions: []
"""


def _config(make_config, automations=OLD_STYLE, extra=None):
    files = {"configuration.yaml": "automation: !include automations.yaml\n", "automations.yaml": automations}
    files.update(extra or {})
    return make_config(files)


def test_tidy_writes_a_corrected_copy_and_never_touches_the_original(make_config, tmp_path):
    root = _config(make_config, extra={"secrets.yaml": "pw: never-copy-me\n"})
    before = folder_fingerprint(root)
    report = tidy(examine(root), tmp_path / "out")
    write_change_log(report, examine(root))
    assert folder_fingerprint(root) == before
    new = (tmp_path / "out" / "automations.yaml").read_text(encoding="utf-8")
    assert "service:" not in new and "platform:" not in new and "data_template" not in new
    assert "triggers:" in new and "actions:" in new and "- action: light.turn_on" in new and "trigger: state" in new
    assert new.startswith("# My automations\n- id: hall_light\n  alias: Hall light\n")  # standard order, list at the left edge
    assert not (tmp_path / "out" / "secrets.yaml").exists()
    assert (tmp_path / "out" / MARKER).exists()
    log = (tmp_path / "out" / "CHANGES.md").read_text(encoding="utf-8")
    assert "Changed \"service: light.turn_on\" to \"action: light.turn_on\"" in log and "2024.8" in log
    assert "never-copy-me" not in log


def test_tidied_file_means_the_same_to_home_assistant(make_config, tmp_path):
    root = _config(make_config)
    tidy(examine(root), tmp_path / "out")
    old = to_plain(parse_yaml(OLD_STYLE, "a").data)
    new = to_plain(parse_yaml((tmp_path / "out" / "automations.yaml").read_text(encoding="utf-8"), "a").data)
    first = old[0]
    first["triggers"] = [{"trigger" if k == "platform" else k: v for k, v in t.items()} for t in first.pop("trigger")]
    actions = first.pop("action")
    actions[0]["action"] = actions[0].pop("service")
    actions[0]["data"] = actions[0].pop("data_template")
    actions[1]["wait_for_trigger"] = [{"trigger" if k == "platform" else k: v for k, v in t.items()} for t in actions[1]["wait_for_trigger"]]
    first["actions"] = actions
    assert same_meaning(old, new)


def test_tidying_twice_changes_nothing_more(make_config, tmp_path):
    root = _config(make_config)
    tidy(examine(root), tmp_path / "once")
    again = _config(make_config, automations=(tmp_path / "once" / "automations.yaml").read_text(encoding="utf-8"))
    report = tidy(examine(again), tmp_path / "twice")
    assert report.changed == []


def test_comments_are_kept_and_order_left_alone_when_comments_are_inside(make_config, tmp_path):
    text = ("- alias: With comments\n  id: c1\n  # why this exists\n  trigger:\n    platform: sun  # at dusk\n"
            "    event: sunset\n  action:\n    - service: light.turn_on  # porch\n")
    root = _config(make_config, automations=text)
    report = tidy(examine(root), tmp_path / "out")
    new = (tmp_path / "out" / "automations.yaml").read_text(encoding="utf-8")
    assert comment_texts(new) == comment_texts(text)
    assert new.index("alias") < new.index("id: c1")  # not reordered: comments inside
    assert "triggers:" in new and "trigger: sun" in new and "action: light.turn_on" in new
    assert "Key order left as it was" in report.changed[0].note or report.changed[0].note == ""


def test_uncertain_files_are_left_alone(make_config, tmp_path):
    root = make_config({
        "configuration.yaml": "automation: !include automations.yaml\nother: !include broken.yaml\n",
        "automations.yaml": "- id: a\n  alias: A\n  mode: single\n  mode: restart\n  trigger: []\n  action: []\n",
        "broken.yaml": "a:\n\tb: 1\n",
    })
    report = tidy(examine(root), tmp_path / "out")
    skipped = {f.rel: f.reason for f in report.skipped}
    assert "same setting twice" in skipped["automations.yaml"]
    assert "layout mistake" in skipped["broken.yaml"]
    assert not (tmp_path / "out" / "automations.yaml").exists()


def test_variables_keep_their_order_and_both_keys_are_not_merged(make_config, tmp_path):
    text = ("- id: v\n  alias: V\n  variables:\n    b: 1\n    a: \"{{ b + 1 }}\"\n  trigger: []\n  triggers: []\n  actions: []\n")
    root = _config(make_config, automations=text)
    tidy(examine(root), tmp_path / "out")
    new_path = tmp_path / "out" / "automations.yaml"
    new = new_path.read_text(encoding="utf-8") if new_path.exists() else text
    assert new.index("b: 1") < new.index("a: ")
    assert "trigger: []" in new and "triggers: []" in new  # both present: reported, never auto-merged


def test_windows_line_endings_and_byte_order_mark(make_config, tmp_path):
    root = _config(make_config, automations="- id: a\r\n  alias: A\r\n  triggers: []\r\n  actions: []\r\n")
    (root / "automations.yaml").write_bytes(b"\xef\xbb\xbf" + (root / "automations.yaml").read_bytes())
    report = tidy(examine(root), tmp_path / "out")
    data = (tmp_path / "out" / "automations.yaml").read_bytes()
    assert b"\r\n" not in data and not data.startswith(b"\xef\xbb\xbf")
    whats = " ".join(c.what for c in report.changed[0].changes)
    assert "byte order mark" in whats and "line endings" in whats


def test_named_sections_sorted_only_when_safe(make_config, tmp_path):
    root = make_config({"configuration.yaml": "input_boolean:\n  zebra: {}\n  apple: {}\nscript: !include scripts.yaml\n",
                        "scripts.yaml": "zz:\n  sequence: []\n# keep me here\naa:\n  sequence: []\n"})
    tidy(examine(root), tmp_path / "out")
    config = (tmp_path / "out" / "configuration.yaml").read_text(encoding="utf-8")
    assert config.index("apple") < config.index("zebra")
    scripts_path = tmp_path / "out" / "scripts.yaml"
    scripts = scripts_path.read_text(encoding="utf-8") if scripts_path.exists() else (root / "scripts.yaml").read_text(encoding="utf-8")
    assert scripts.index("zz") < scripts.index("aa")  # has a comment, so left in its order


def test_keep_order_option(make_config, tmp_path):
    root = _config(make_config)
    tidy(examine(root), tmp_path / "out", keep_order=True)
    new = (tmp_path / "out" / "automations.yaml").read_text(encoding="utf-8")
    assert new.index("alias: Hall light") < new.index("id: hall_light")


def test_output_folder_rules(make_config, tmp_path):
    root = _config(make_config)
    with pytest.raises(OutputFolderProblem):
        check_output_folder(root, root / "tidied")
    with pytest.raises(OutputFolderProblem):
        check_output_folder(root, root.parent)
    busy = tmp_path / "busy"
    busy.mkdir()
    (busy / "something.txt").write_text("x", encoding="utf-8")
    with pytest.raises(OutputFolderProblem):
        check_output_folder(root, busy)
    tidy(examine(root), tmp_path / "ours")
    check_output_folder(root, tmp_path / "ours")  # a folder we made before is fine to reuse


def test_same_meaning_is_strict():
    assert same_meaning({"a": 1, "b": [True]}, {"b": [True], "a": 1})
    assert not same_meaning({"a": 1}, {"a": True})
    assert not same_meaning({"a": "1"}, {"a": 1})
    assert not same_meaning({"variables": {"a": 1, "b": 2}}, {"variables": {"b": 2, "a": 1}})


def test_tidy_text_refuses_meaning_changes(monkeypatch):
    import ha_config_doctor.tidy as tidy_module

    real_dump = tidy_module._dump
    monkeypatch.setattr(tidy_module, "_dump", lambda data: real_dump(data).replace("'on'", "on"))
    result = tidy_text("- id: a\n  alias: A\n  triggers:\n  - trigger: state\n    entity_id: light.a\n    to: 'on'\n  actions: []\n",
                       "a.yaml", Targets(set(), set(), set()))
    assert result.status == "skipped"
