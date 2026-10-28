"""Following !include the way Home Assistant does, and never reading secret values."""

from ha_config_doctor.catalog import Findings
from ha_config_doctor.configtree import ConfigSet, scan_top_level_names
from ha_config_doctor.yamlio import to_plain

from .conftest import codes, findings_for


def load(path):
    findings = Findings()
    return ConfigSet(path, findings).load(), findings


def test_include_variants(make_config):
    root = make_config({
        "configuration.yaml": """
            one: !include one.yaml
            listed: !include_dir_list d
            named: !include_dir_named d
            merged_list: !include_dir_merge_list lists
            merged_named: !include_dir_merge_named d
            absolute: !include /config/one.yaml
        """,
        "one.yaml": "value: 1\n",
        "d/a.yaml": "x: 1\n",
        "d/b.yaml": "y: 2\n",
        "d/.hidden.yaml": "hidden: true\n",
        "d/secrets.yaml": "never: read\n",
        "lists/1.yaml": "- 1\n- 2\n",
        "lists/2.yaml": "- 3\n",
    })
    config, findings = load(root)
    plain = to_plain(config.config)
    assert plain["one"] == {"value": 1}
    assert plain["absolute"] == {"value": 1}
    assert plain["listed"] == [{"x": 1}, {"y": 2}]
    assert plain["named"] == {"a": {"x": 1}, "b": {"y": 2}}
    assert plain["merged_list"] == [1, 2, 3]
    assert plain["merged_named"] == {"x": 1, "y": 2}
    assert "d/secrets.yaml" not in config.files
    assert "d/.hidden.yaml" not in config.files


def test_yml_files_are_ignored_in_include_folders(make_config):
    root = make_config({"configuration.yaml": "pkgs: !include_dir_named packages\n",
                        "packages/a.yaml": "x: 1\n", "packages/b.yml": "y: 2\n"})
    config, findings = load(root)
    assert to_plain(config.config["pkgs"]) == {"a": {"x": 1}}
    assert "yml-ignored" in findings.codes()


def test_missing_wrong_case_outside_and_loops(make_config):
    root = make_config({
        "configuration.yaml": """
            a: !include missing.yaml
            b: !include Groups.yaml
            c: !include ../elsewhere.yaml
            d: !include loop1.yaml
            e: !include_dir_named no_such_folder
        """,
        "groups.yaml": "g: 1\n",
        "loop1.yaml": "x: !include loop2.yaml\n",
        "loop2.yaml": "y: !include loop1.yaml\n",
    })
    config, findings = load(root)
    missing = [f for f in findings.items if f.code == "include-missing"]
    assert len(missing) == 3
    assert any("capital" in f.detail for f in missing)
    assert {"include-outside-folder", "include-loop"} <= findings.codes()


def test_merge_folders_skip_the_wrong_shape(make_config):
    root = make_config({"configuration.yaml": "a: !include_dir_merge_list l\nb: !include_dir_merge_named n\n",
                        "l/ok.yaml": "- 1\n", "l/bad.yaml": "not: a list\n",
                        "n/ok.yaml": "k: 1\n", "n/bad.yaml": "- not named\n", "n/dup.yaml": "k: 2\n"})
    config, findings = load(root)
    assert to_plain(config.config["a"]) == [1]
    assert len([f for f in findings.items if f.code == "include-wrong-content"]) == 2
    assert "duplicate-key" in findings.codes()


def test_secret_names_are_checked_without_reading_values(make_config):
    root = make_config({
        "configuration.yaml": "a: !secret known_name\nb: !secret unknown_name\nsub: !include sub/x.yaml\n",
        "secrets.yaml": 'known_name: "super-private-value"\n"quoted name": also-private\nindented:\n  child: x\n',
        "sub/x.yaml": "c: !secret known_name\n",
    })
    config, findings = load(root)
    assert scan_top_level_names(root / "secrets.yaml") == {"known_name", "quoted name", "indented"}
    missing = [f for f in findings.items if f.code == "secret-missing"]
    assert len(missing) == 1 and "unknown_name" in missing[0].detail
    assert "secrets.yaml" not in config.files  # never parsed
    assert all("super-private-value" not in f.detail for f in findings.items)


def test_secrets_file_missing(make_config):
    root = make_config({"configuration.yaml": "a: !secret x\n"})
    _, findings = load(root)
    assert "secrets-file-missing" in findings.codes()


def test_secrets_yaml_is_never_included(make_config):
    root = make_config({"configuration.yaml": "s: !include secrets.yaml\n", "secrets.yaml": "pw: private\n"})
    config, findings = load(root)
    assert "secrets-included" in findings.codes()
    assert config.config["s"] is None


def test_env_var_unknown_tag_and_input(make_config):
    root = make_config({"configuration.yaml": "a: !env_var X\nb: !env_var Y fallback\nc: !inclde x.yaml\nd: !input z\n"})
    _, findings = load(root)
    assert len([f for f in findings.items if f.code == "env-var-used"]) == 1
    assert {"unknown-tag", "input-outside-blueprint"} <= findings.codes()


def test_unused_files_and_unconnected_ui_files(make_config):
    root = make_config({"configuration.yaml": "x: 1\n", "automations.yaml": "[]\n", "old.yaml": "a: 1\n",
                        "esphome/device.yaml": "esphome: {}\n", "secrets.yaml": "a: b\n"})
    config, findings = load(root)
    assert [f.file for f in findings.items if f.code == "file-not-used"] == ["old.yaml"]
    assert "ui-file-not-included" in findings.codes()


def test_bad_text_and_layout_errors(make_config):
    root = make_config({"configuration.yaml": "a: !include latin.yaml\nb: !include broken.yaml\n",
                        "latin.yaml": b"name: caf\xe9\n", "broken.yaml": "a:\n\tb: 1\n"})
    _, findings = load(root)
    assert {"file-not-utf8", "yaml-syntax-error"} <= findings.codes()
    error = [f for f in findings.items if f.code == "yaml-syntax-error"][0]
    assert error.file == "broken.yaml" and error.line == 2


def test_no_configuration_yaml(run):
    result = run({"notes.txt": "hello"})
    assert "no-configuration-yaml" in codes(result)


def test_packages_and_labelled_sections(run):
    result = run({
        "configuration.yaml": "homeassistant:\n  packages: !include_dir_named packages\nautomation old: !include old.yaml\n",
        "packages/p.yaml": "automation:\n  - id: p1\n    alias: From package\n    triggers: []\n    actions: []\n",
        "old.yaml": "- id: o1\n  alias: Labelled\n  triggers: []\n  actions: []\n",
    })
    aliases = {a.alias for a in result.model.automations}
    assert aliases == {"From package", "Labelled"}
    assert findings_for(result, "no-triggers")
