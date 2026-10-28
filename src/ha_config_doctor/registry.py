"""Read Home Assistant's own lists of entities and devices from the hidden .storage folder.

Strictly read-only, and strictly limited: we open only the files named in
:data:`ALLOWED_FILES`. Files that hold logins, tokens or passwords — such as
``auth``, ``auth_provider.homeassistant``, ``core.config_entries``, ``cloud``,
``http`` or ``application_credentials`` — are never opened.

From each file we keep only what the checks need (entity names, whether they
are disabled, which device they belong to). Everything else, including any
attribute values in the saved states, is dropped straight away and never
written anywhere.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .util import HELPER_DOMAINS, KNOWN_DOMAINS

HELPER_STORES = HELPER_DOMAINS + ("person", "zone")
ALLOWED_FILES = frozenset(
    {"core.entity_registry", "core.device_registry", "core.restore_state", "core.config", "lovelace"}
    | set(HELPER_STORES)
)
NEVER_OPENED = (
    "auth", "auth_provider.homeassistant", "core.config_entries", "cloud", "http",
    "application_credentials", "onboarding", "core.uuid", "hassio", "backup",
)

_MENTION = re.compile(r"\b(" + "|".join(sorted(KNOWN_DOMAINS, key=len, reverse=True)) + r")\.([a-z0-9_]+)\b")


@dataclass
class RegEntity:
    entity_id: str
    registry_id: str
    platform: str
    unique_id: str
    device_id: str | None
    config_entry_id: str | None
    disabled_by: str | None
    hidden_by: str | None


def _allowed(name: str) -> bool:
    return name in ALLOWED_FILES or name.startswith("lovelace.")


class Registry:
    def __init__(self, root: Path) -> None:
        self.storage = Path(root) / ".storage"
        self.has_storage = self.storage.is_dir()
        self.entities: dict[str, RegEntity] = {}
        self.by_registry_id: dict[str, str] = {}
        self.by_unique: dict[tuple[str, str], str] = {}
        self.deleted: dict[str, bool] = {}  # entity id -> True when orphaned
        self.devices: dict[str, str | None] | None = None  # device id -> disabled_by
        self.deleted_devices: set[str] = set()
        self.restore: dict[str, str] | None = None  # entity id -> last saved state
        self.helper_ids: dict[str, set[str]] = {}
        self.dashboard_mentions: set[str] = set()
        self.location: tuple[float, float, str | None] | None = None
        self.files_read: list[str] = []
        self.problems: list[str] = []
        if self.has_storage:
            self._load()

    @property
    def has_entities(self) -> bool:
        return "core.entity_registry" in self.files_read

    @property
    def has_devices(self) -> bool:
        return self.devices is not None

    def _read(self, name: str) -> Any:
        if not _allowed(name):  # belt and braces: never open anything else
            raise PermissionError(name)
        path = self.storage / name
        if not path.is_file():
            return None
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError, UnicodeDecodeError):
            self.problems.append(f"{name} could not be read")
            return None
        self.files_read.append(name)
        return data.get("data") if isinstance(data, dict) else None

    def _load(self) -> None:
        data = self._read("core.entity_registry")
        if isinstance(data, dict):
            for item in data.get("entities") or []:
                if not isinstance(item, dict) or not isinstance(item.get("entity_id"), str):
                    continue
                entity = RegEntity(
                    entity_id=item["entity_id"],
                    registry_id=str(item.get("id") or ""),
                    platform=str(item.get("platform") or ""),
                    unique_id=str(item.get("unique_id") or ""),
                    device_id=item.get("device_id"),
                    config_entry_id=item.get("config_entry_id"),
                    disabled_by=item.get("disabled_by"),
                    hidden_by=item.get("hidden_by"),
                )
                self.entities[entity.entity_id] = entity
                if entity.registry_id:
                    self.by_registry_id[entity.registry_id] = entity.entity_id
                if entity.unique_id:
                    self.by_unique[(entity.platform, entity.unique_id)] = entity.entity_id
            for item in data.get("deleted_entities") or []:
                if isinstance(item, dict) and isinstance(item.get("entity_id"), str):
                    self.deleted[item["entity_id"]] = item.get("orphaned_timestamp") is not None
                    if item.get("id"):
                        self.by_registry_id.setdefault(str(item["id"]), item["entity_id"])

        data = self._read("core.device_registry")
        if isinstance(data, dict):
            self.devices = {}
            for item in data.get("devices") or []:
                if isinstance(item, dict) and item.get("id"):
                    self.devices[str(item["id"])] = item.get("disabled_by")
            for item in data.get("deleted_devices") or []:
                if isinstance(item, dict) and item.get("id"):
                    self.deleted_devices.add(str(item["id"]))

        data = self._read("core.restore_state")
        if isinstance(data, list):
            self.restore = {}
            for item in data:
                state = item.get("state") if isinstance(item, dict) else None
                if isinstance(state, dict) and isinstance(state.get("entity_id"), str):
                    # keep only the entity name and its state text; attributes are discarded unread
                    self.restore[state["entity_id"]] = str(state.get("state"))

        data = self._read("core.config")
        if isinstance(data, dict):
            lat, lon = data.get("latitude"), data.get("longitude")
            if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                # rounded straight away: about 10 km is plenty for sunrise and sunset times
                self.location = (round(float(lat), 1), round(float(lon), 1), data.get("time_zone"))

        for domain in HELPER_STORES:
            data = self._read(domain)
            if isinstance(data, dict):
                ids = {str(item["id"]) for item in data.get("items") or [] if isinstance(item, dict) and item.get("id")}
                self.helper_ids[domain] = ids

        for path in sorted(self.storage.iterdir()):
            name = path.name
            if name == "lovelace" or (name.startswith("lovelace.") and _allowed(name)):
                data = self._read(name)
                if data is not None:
                    text = json.dumps(data)
                    self.dashboard_mentions |= {f"{m.group(1)}.{m.group(2)}" for m in _MENTION.finditer(text)}

    # ------------------------------------------------------------------
    def entity_for_registry_id(self, value: str) -> str | None:
        return self.by_registry_id.get(value)

    def entity_ids_in_domain(self, domain: str) -> set[str]:
        return {eid for eid in self.entities if eid.startswith(domain + ".")}
