"""The samples set off every check, the healthy sample sets off none, and the repository holds no personal data."""

import re
import subprocess

from ha_config_doctor.catalog import CHECKS
from ha_config_doctor.doctor import examine
from ha_config_doctor.redact import redact_text, shown_value

from .conftest import REPO, SAMPLES

FAULTY_SAMPLES = ("faulty-config", "no-storage-config", "not-a-config-folder")


def test_every_check_is_triggered_by_the_samples():
    triggered = set()
    for name in FAULTY_SAMPLES:
        result = examine(SAMPLES / name)
        assert result.unfinished == []
        triggered |= result.findings.codes()
    assert set(CHECKS) - triggered == set()


def test_healthy_sample_has_no_findings():
    result = examine(SAMPLES / "healthy-config")
    assert result.unfinished == []
    assert [(f.code, f.file, f.line, f.detail) for f in result.findings.items] == []
    assert result.registry.has_entities and len(result.model.automations) == 7


def test_healthy_sample_tidies_without_skipping_anything(tmp_path):
    from ha_config_doctor.tidy import tidy

    report = tidy(examine(SAMPLES / "healthy-config"), tmp_path / "out")
    assert report.skipped == []


def test_every_severity_is_used():
    severities = {f.severity for f in examine(SAMPLES / "faulty-config").findings.items}
    assert severities == {"Error", "Warning", "Tidy-up"}


# ------------------------------------------------------------------ redaction

def test_redaction_hides_private_looking_text():
    token = "eyJ" + "a" * 20 + "." + "b" * 20 + "." + "c" * 20
    mixed = "Ab3" * 10
    text = (f"ip 192.0.2.44, v6 2001:db8::1, mail person@example.org, url https://user:pw@example.com/x, "
            f"jwt {token}, key {mixed}, phone +441632960961, password: hunter2, hex {'f' * 32}")
    out = redact_text(text)
    for secret in ("192.0.2.44", "2001:db8::1", "person@example.org", "user:pw", token, mixed, "+441632960961", "hunter2", "f" * 32):
        assert secret not in out
    for kept in ("light.kitchen_ceiling", "07:30:00", "2026.10.1", "1700000000001", "binary_sensor.hall_motion"):
        assert redact_text(kept) == kept


def test_sensitive_settings_are_never_shown():
    assert shown_value("password", "abc") == "[hidden]"
    assert shown_value("api_key", "abc") == "[hidden]"
    assert shown_value("latitude", 52.1) == "[hidden]"
    assert shown_value("brightness", 40) == "40"


# ------------------------------------------------------------------ repository hygiene

def _repository_files():
    listed = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=REPO,
                            capture_output=True, text=True, check=True).stdout.split()
    for rel in listed:
        path = REPO / rel
        if path.is_file():
            yield rel, path.read_bytes().decode("utf-8", errors="replace")


ALLOWED_ADDRESSES = re.compile(r"^(192\.0\.2\.|198\.51\.100\.|203\.0\.113\.|0\.0\.0\.0$|127\.0\.0\.1$)")
IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@([A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+)")


def test_no_real_addresses_emails_or_tokens_in_the_repository():
    for rel, text in _repository_files():
        for address in IPV4.findall(text):
            assert ALLOWED_ADDRESSES.match(address), f"{rel}: {address}"
        for domain in EMAIL.findall(text):
            assert domain.lower() in ("example.com", "example.org", "example.net"), f"{rel}: {domain}"
        assert not re.search(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.", text), rel


def test_sample_secrets_are_obviously_fake():
    for secrets in SAMPLES.rglob("secrets.yaml"):
        for line in secrets.read_text(encoding="utf-8").splitlines():
            if ":" in line and not line.lstrip().startswith("#"):
                value = line.split(":", 1)[1].strip().strip('"')
                assert value.startswith("FAKE-") or value in ("0000", "0.0"), f"{secrets}: {line.split(':')[0]}"
