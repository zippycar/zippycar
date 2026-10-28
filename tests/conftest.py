from __future__ import annotations

import hashlib
import json
import textwrap
from pathlib import Path

import pytest

from ha_config_doctor.doctor import Result, examine

REPO = Path(__file__).resolve().parent.parent
SAMPLES = REPO / "samples"


def write_config(root: Path, files: dict[str, str | dict | bytes]) -> Path:
    """Create a configuration folder from {relative path: text (or JSON-able dict for .storage)}."""

    root.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        elif isinstance(content, (dict, list)):
            path.write_bytes(json.dumps(content).encode("utf-8"))
        else:
            # bytes, not text mode: Windows would otherwise turn every line ending into CRLF
            path.write_bytes(textwrap.dedent(content).lstrip("\n").encode("utf-8"))
    return root


def folder_fingerprint(root: Path) -> dict[str, str]:
    """A hash of every file, to prove a folder was not changed."""

    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*")) if p.is_file()
    }


def registry(entities: list[dict] | None = None, deleted: list[dict] | None = None) -> dict:
    return {"version": 1, "minor_version": 18, "key": "core.entity_registry",
            "data": {"entities": entities or [], "deleted_entities": deleted or []}}


def reg_entity(entity_id: str, platform: str = "demo", unique_id: str | None = None, device_id: str | None = None,
               disabled_by: str | None = None, registry_id: str | None = None) -> dict:
    return {"entity_id": entity_id, "platform": platform, "unique_id": unique_id or entity_id, "device_id": device_id,
            "disabled_by": disabled_by, "hidden_by": None, "config_entry_id": None,
            "id": registry_id or hashlib.md5(entity_id.encode()).hexdigest()}


@pytest.fixture
def make_config(tmp_path):
    def _make(files: dict, name: str = "config") -> Path:
        return write_config(tmp_path / name, files)
    return _make


@pytest.fixture
def run(make_config):
    """Build a config folder and examine it."""

    def _run(files: dict) -> Result:
        return examine(make_config(files))
    return _run


def automation_config(automations: str, extra: dict | None = None, storage: list[str] | None = None) -> dict:
    """A minimal config: configuration.yaml including automations.yaml with the given text."""

    files: dict = {
        "configuration.yaml": "automation: !include automations.yaml\nscript: !include scripts.yaml\n",
        "automations.yaml": automations,
        "scripts.yaml": "{}\n",
    }
    if storage is not None:
        files[".storage/core.entity_registry"] = registry([reg_entity(e) for e in storage])
    files.update(extra or {})
    return files


def codes(result: Result) -> set[str]:
    return result.findings.codes()


def findings_for(result: Result, code: str) -> list:
    return [f for f in result.findings.items if f.code == code]
