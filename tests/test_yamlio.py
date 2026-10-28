"""The YAML reader must see files exactly as Home Assistant does."""

from pathlib import Path

from ha_config_doctor.yamlio import HATag, LList, LMap, LStr, parse_yaml, read_text, to_plain


def test_yaml_1_1_rules_like_home_assistant():
    parsed = parse_yaml("a: on\nb: 'on'\nc: 7:30\nd: 07:30\ne: yes\nf: 12:30:00\n", "f.yaml")
    data = parsed.data
    assert data["a"] is True  # unquoted on is a boolean, as in Home Assistant
    assert data["b"] == "on"
    assert data["c"] == 450  # sexagesimal: 7*60 + 30
    assert data["d"] == "07:30"  # a leading zero keeps it as text
    assert data["e"] is True
    assert data["f"] == 45000
    assert data.raw_of("a").text == "on" and data.raw_of("a").style is None


def test_every_item_knows_its_line_and_file():
    parsed = parse_yaml("# comment\nfirst: 1\nsecond:\n  - x\n  - y: 2\n", "dir/file.yaml")
    data = parsed.data
    assert isinstance(data, LMap) and data.file == "dir/file.yaml"
    assert data.key_line("first") == 2
    assert data.key_line("second") == 3
    assert isinstance(data["second"], LList)
    assert data["second"].item_line(0) == 4
    assert data["second"].item_line(1) == 5
    assert isinstance(data["second"][0], LStr) and data["second"][0].line == 4
    assert data["second"][1].line == 5


def test_duplicate_keys_are_recorded_and_the_last_wins():
    parsed = parse_yaml("mode: single\nmode: restart\n", "f.yaml")
    assert parsed.data["mode"] == "restart"
    assert parsed.duplicates == [("mode", 1, 2)]


def test_merge_keys_are_not_duplicates():
    parsed = parse_yaml("base: &b {k: 1, j: 2}\nthing:\n  <<: *b\n  k: 3\n", "f.yaml")
    assert parsed.duplicates == []
    assert to_plain(parsed.data["thing"]) == {"k": 3, "j": 2}


def test_home_assistant_tags_are_kept():
    text = ("a: !include x.yaml\nb: !include_dir_list d\nc: !include_dir_named d\nd: !include_dir_merge_list d\n"
            "e: !include_dir_merge_named d\nf: !secret pw\ng: !input name\nh: !env_var HOME_X fallback\n")
    data = parse_yaml(text, "f.yaml").data
    tags = {key: (value.tag, value.value) for key, value in data.items()}
    assert tags == {
        "a": ("!include", "x.yaml"), "b": ("!include_dir_list", "d"), "c": ("!include_dir_named", "d"),
        "d": ("!include_dir_merge_list", "d"), "e": ("!include_dir_merge_named", "d"), "f": ("!secret", "pw"),
        "g": ("!input", "name"), "h": ("!env_var", "HOME_X fallback"),
    }
    assert all(isinstance(v, HATag) and v.line for v in data.values())


def test_unknown_tags_do_not_crash():
    data = parse_yaml("x: !something value\n", "f.yaml").data
    assert data["x"].tag == "!something"


def test_layout_problems_are_explained_in_plain_english():
    problem = parse_yaml("a:\n\tb: 1\n", "f.yaml").problem
    assert problem.line == 2 and "TAB" in problem.message
    problem = parse_yaml("a: b: c\n", "f.yaml").problem
    assert problem.line == 1 and "colon" in problem.message


def test_problem_text_never_contains_file_contents():
    problem = parse_yaml("password: hunter-secret-value: oops\n", "f.yaml").problem
    assert problem is not None
    assert "hunter-secret-value" not in problem.message + problem.technical


def test_byte_order_mark_is_ignored(tmp_path: Path):
    path = tmp_path / "f.yaml"
    path.write_bytes(b"\xef\xbb\xbfa: 1\n")
    assert parse_yaml(read_text(path), "f.yaml").data == {"a": 1}


def test_empty_document():
    assert parse_yaml("# only a comment\n", "f.yaml").data is None
