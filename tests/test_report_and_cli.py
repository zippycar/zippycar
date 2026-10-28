"""Reports, the change log and the command line."""

import re
from pathlib import Path

import pytest

from ha_config_doctor import __version__
from ha_config_doctor.catalog import CHECKS
from ha_config_doctor.cli import _clean_path, main
from ha_config_doctor.doctor import examine
from ha_config_doctor.report import checks_markdown, render_html, render_markdown
from ha_config_doctor.sun import yearly_ranges

from .conftest import REPO, SAMPLES, automation_config, folder_fingerprint


def test_reports_start_with_a_summary_and_group_by_severity():
    result = examine(SAMPLES / "faulty-config")
    md = render_markdown(result)
    html = render_html(result)
    for text in (md, html):
        summary = text.index("Summary") if "## Summary" in text else text.index("Start here")
        errors, warnings, tidy = text.index("Errors — fix these first"), text.index("Warnings — worth a look"), text.index("Tidy-ups — when you have time")
        assert summary < errors < warnings < tidy
        assert "automations.yaml, line " in text
        assert "Why this matters:" in text and "How to fix it:" in text
    assert 'class="summary"' in html and "break-after: page" in html


def test_every_finding_has_a_file_line_explanation_and_fix():
    result = examine(SAMPLES / "faulty-config")
    md = render_markdown(result)
    for finding in result.findings.items:
        assert finding.check.why and finding.suggested_fix
        if finding.file:
            assert finding.file in md


def test_html_escapes_everything(run):
    text = '- id: x\n  alias: "<script>alert(1)</script>"\n  triggers: []\n  actions: []\n'
    html = render_html(run(automation_config(text)))
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


def test_no_secret_ever_reaches_any_output(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["check", str(SAMPLES / "faulty-config")]) == 1
    assert main(["tidy", str(SAMPLES / "faulty-config"), str(tmp_path / "tidied")]) == 0
    printed = capsys.readouterr().out
    outputs = [printed] + [p.read_text(encoding="utf-8") for p in (tmp_path / "ha-config-doctor-report").iterdir()]
    outputs += [(tmp_path / "tidied" / name).read_text(encoding="utf-8") for name in ("CHANGES.md", "CHANGES.html")]
    secrets = ["FAKE-sample-password-123", "FAKE-sample-password-789", "inline-fake-password-456",
               "alerts@example.com", "someone@example.com", "0123456789abcdef0123456789abcdef"]
    for text in outputs:
        for secret in secrets:
            assert secret not in text
    assert not (tmp_path / "tidied" / "secrets.yaml").exists()
    for path in (tmp_path / "tidied").rglob("*.yaml"):
        assert "FAKE-sample-password" not in path.read_text(encoding="utf-8")


def test_check_never_changes_the_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for sample in ("faulty-config", "healthy-config", "no-storage-config"):
        before = folder_fingerprint(SAMPLES / sample)
        main(["check", str(SAMPLES / sample)])
        main(["tidy", str(SAMPLES / sample), str(tmp_path / f"tidied-{sample}")])
        assert folder_fingerprint(SAMPLES / sample) == before


def test_exit_codes_and_report_location(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["check", str(SAMPLES / "healthy-config")]) == 0
    assert (tmp_path / "ha-config-doctor-report" / "report.html").exists()
    assert main(["check", str(tmp_path / "does-not-exist")]) == 2
    monkeypatch.chdir(SAMPLES / "healthy-config")
    assert main(["check", "."]) == 2  # would write the report inside the config folder
    assert "never writes there" in capsys.readouterr().out
    assert main(["check", str(SAMPLES / "healthy-config"), "--report-folder", str(tmp_path / "elsewhere")]) == 0
    assert (tmp_path / "elsewhere" / "report.md").exists()


def test_pointing_at_configuration_yaml_itself_works(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["check", str(SAMPLES / "healthy-config" / "configuration.yaml")]) == 0


def test_tidy_refuses_unsafe_output_folders(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["tidy", str(SAMPLES / "healthy-config"), str(SAMPLES / "healthy-config" / "tidied")]) == 2
    assert "can't go inside your configuration folder" in capsys.readouterr().out


def test_copy_paste_slips_in_paths_are_forgiven():
    assert _clean_path('  "C:\\HA Copy\\config\\"  ') == Path("C:\\HA Copy\\config")
    assert _clean_path("'/tmp/config/'") == Path("/tmp/config")


def test_list_checks_and_version(capsys):
    assert main(["list-checks"]) == 0
    out = capsys.readouterr().out
    assert f"{len(CHECKS)} checks in total" in out
    with pytest.raises(SystemExit):
        main(["--version"])
    assert __version__ in capsys.readouterr().out


def test_docs_checks_file_is_up_to_date():
    assert (REPO / "docs" / "CHECKS.md").read_text(encoding="utf-8") == checks_markdown() + "\n"


def test_every_check_is_written_in_plain_english():
    jargon = re.compile(r"\b(regex|stack ?trace|exception|parse[rd]?|boolean|deprecat\w*|schema|null|syntax)\b", re.I)
    for check in CHECKS.values():
        for text in (check.title, check.why, check.fix):
            assert text.strip() and not jargon.search(text), (check.code, text)
        for sentence in (check.why, check.fix):
            assert sentence.rstrip()[-1] in '.)"', (check.code, sentence)


def test_sun_times_are_sensible():
    ranges = yearly_ranges((52.0, -1.0, "Europe/London"))
    earliest_sunset, latest_sunset = ranges["sunset"]
    assert 15 * 3600 + 30 * 60 < earliest_sunset < 16 * 3600 + 15 * 60
    assert 21 * 3600 < latest_sunset < 21 * 3600 + 45 * 60
    earliest_rise, latest_rise = ranges["sunrise"]
    assert 4 * 3600 + 30 * 60 < earliest_rise < 5 * 3600 and 8 * 3600 < latest_rise < 8 * 3600 + 30 * 60
    assert yearly_ranges(None)["sunset"] == (15 * 3600 + 30 * 60, 22 * 3600 + 30 * 60)
