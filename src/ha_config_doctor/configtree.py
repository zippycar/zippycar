"""Find and read every file Home Assistant would read, following !include the same way it does.

Rules copied from Home Assistant's own loader:

* paths in ``!include`` are relative to the file that contains them;
* the ``!include_dir_…`` commands read only files ending in ``.yaml`` (not
  ``.yml``), skip files and folders whose names start with a dot, and skip
  ``secrets.yaml``;
* ``!include_dir_merge_list`` silently ignores files that aren't lists and
  ``!include_dir_merge_named`` ignores files that aren't named blocks;
* ``!secret`` looks in ``secrets.yaml`` next to the file, then in each parent
  folder up to the config folder.

Privacy: ``secrets.yaml`` is never parsed. We only look at the start of each
line to learn which *names* exist; the values are thrown away unread.
"""

from __future__ import annotations

import os
import posixpath
import re
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from .catalog import Findings
from .util import quote_list
from .yamlio import INCLUDE_TAGS, HATag, LList, LMap, NotUtf8, ParsedYaml, parse_yaml, read_text

SECRETS_FILE = "secrets.yaml"

# Folders at the top of the config folder that belong to other things (add-ons,
# downloads, the web folder…). We don't read YAML files inside them.
FOREIGN_DIRS = {
    "blueprints", "custom_components", "www", "esphome", "zigbee2mqtt", "node-red", "nodered",
    "appdaemon", "tts", "deps", "backups", "backup", "image", "python_scripts", "netdaemon",
    "pyscript", "media", "music_assistant", "matter_server", "share", "ssl", "addons",
}
# Files Home Assistant reads by itself, or that we deliberately never open.
SPECIAL_FILES = {
    "configuration.yaml", SECRETS_FILE, "known_devices.yaml", "ip_bans.yaml",
    "ui-lovelace.yaml", "google_calendars.yaml",
}
UI_FILES = {
    "automations.yaml": "automation: !include automations.yaml",
    "scripts.yaml": "script: !include scripts.yaml",
    "scenes.yaml": "scene: !include scenes.yaml",
}

_NAME_AT_LINE_START = re.compile(r"""^(?:"([^"\n]+)"|'([^'\n]+)'|([^\s#'"\-{\[][^:#\n]*?))[ \t]*:(?=\s|$)""")


def scan_top_level_names(path: Path) -> set[str]:
    """The names at the very start of each line of a YAML file — never the values.

    Used for secrets.yaml (to check !secret names exist without reading any
    password) and known_devices.yaml.
    """

    names: set[str] = set()
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line in handle:
            if not line or line[0] in " \t#\r\n-":
                continue
            match = _NAME_AT_LINE_START.match(line)
            if match:
                names.add((match.group(1) or match.group(2) or match.group(3)).strip())
            # the rest of the line (the value) is deliberately discarded
    return names


@dataclass
class SourceFile:
    rel: str
    parsed: ParsedYaml
    role: str  # "config", "blueprint" or "dashboard"


class ConfigSet:
    """Everything read from one configuration folder."""

    def __init__(self, root: Path, findings: Findings) -> None:
        self.root = Path(root).resolve()
        self.findings = findings
        self.files: dict[str, SourceFile] = {}
        self.config: LMap = LMap()
        self.blueprints: dict[str, Any] = {}
        self.dashboards: list[Any] = []
        self.secret_refs: list[HATag] = []
        self.input_refs: list[tuple[HATag, str]] = []
        self.known_device_names: set[str] = set()
        self.ha_version: str | None = None
        self.has_configuration = False
        self.ignored_yml: set[str] = set()
        self.unused_files: list[str] = []
        self._resolved: dict[str, Any] = {}
        self._secret_cache: dict[str, set[str] | None] = {}
        self._role = "config"

    # ------------------------------------------------------------------ loading
    def load(self) -> "ConfigSet":
        version_file = self.root / ".HA_VERSION"
        if version_file.is_file():
            try:
                self.ha_version = version_file.read_text(encoding="utf-8", errors="replace").strip()[:40] or None
            except OSError:
                self.ha_version = None
        if (self.root / "configuration.yaml").is_file():
            self.has_configuration = True
            data = self._load("configuration.yaml", ())
            if isinstance(data, LMap):
                self.config = data
            elif data is not None:
                self.findings.add("wrong-include-type", "configuration.yaml", 1,
                                  "configuration.yaml should be a set of named sections (like  automation:  and  script:), but it isn't.")
        else:
            self.findings.add("no-configuration-yaml", "", 0, f'The folder "{self.root.name}" has no configuration.yaml in it.')
        self._check_secrets()
        known = self.root / "known_devices.yaml"
        if known.is_file():
            self.known_device_names = scan_top_level_names(known)
        self._load_blueprints()
        self._check_inputs()
        self._load_dashboards()
        self._check_ui_files()
        self._find_unused_files()
        return self

    def used_files(self, role: str | None = None) -> list[str]:
        return [rel for rel, src in self.files.items() if role is None or src.role == role]

    def _load(self, rel: str, stack: tuple[str, ...]) -> Any:
        if rel in self._resolved:
            return self._resolved[rel]
        path = self.root / rel
        try:
            text = read_text(path)
        except NotUtf8:
            self.findings.add("file-not-utf8", rel, 1, f'"{rel}" contains characters that aren\'t UTF-8 text.')
            self._resolved[rel] = None
            return None
        except OSError:
            self.findings.add("include-missing", rel, 0, f'"{rel}" could not be opened.')
            self._resolved[rel] = None
            return None
        parsed = parse_yaml(text, rel)
        self.files[rel] = SourceFile(rel, parsed, self._role)
        if parsed.problem:
            self.findings.add("yaml-syntax-error", rel, parsed.problem.line,
                              f"{parsed.problem.message} (Technical detail: {parsed.problem.technical}.)")
            self._resolved[rel] = None
            return None
        for key, first, second in parsed.duplicates:
            self.findings.add("duplicate-key", rel, second,
                              f'"{key}" appears on line {first} and again on line {second}. Only the one on line {second} is used.')
        data = parsed.data
        if data is None:
            data = LMap()  # Home Assistant treats an empty file as an empty set of settings
            data.file, data.line = rel, 1
        self._resolved[rel] = data
        data = self._resolve(data, rel, stack + (rel,))
        self._resolved[rel] = data
        return data

    def _resolve(self, value: Any, rel: str, stack: tuple[str, ...]) -> Any:
        if isinstance(value, HATag):
            return self._resolve_tag(value, rel, stack)
        if isinstance(value, LMap):
            for key in list(value.keys()):
                value[key] = self._resolve(value[key], rel, stack)
        elif isinstance(value, LList):
            for index, item in enumerate(value):
                value[index] = self._resolve(item, rel, stack)
        return value

    def _resolve_tag(self, tag: HATag, rel: str, stack: tuple[str, ...]) -> Any:
        if tag.tag in INCLUDE_TAGS:
            return self._include(tag, rel, stack)
        if tag.tag == "!secret":
            self.secret_refs.append(tag)
        elif tag.tag == "!input":
            self.input_refs.append((tag, self._role))
        elif tag.tag == "!env_var":
            parts = tag.text.split()
            if len(parts) < 2:
                self.findings.add("env-var-used", tag.file, tag.line,
                                  f'!env_var {parts[0] if parts else ""} has no default value.'.replace("  ", " "))
        else:
            self.findings.add("unknown-tag", tag.file, tag.line, f'"{tag.tag}" is not a command Home Assistant knows.')
        return tag

    # ------------------------------------------------------------------ includes
    def _target(self, rel: str, value: str) -> tuple[str | None, str | None]:
        text = (value or "").strip().replace("\\", "/")
        base = posixpath.dirname(rel)
        if not text:
            return None, "empty"
        for prefix in ("/config", "/homeassistant"):
            if text == prefix or text.startswith(prefix + "/"):
                text = text[len(prefix):].lstrip("/") or "."
                base = ""
                break
        if text.startswith("/") or re.match(r"^[A-Za-z]:", text):
            return None, "outside"
        joined = posixpath.normpath(posixpath.join(base, text))
        if joined == ".." or joined.startswith("../"):
            return None, "outside"
        return joined, None

    def exact_status(self, rel: str) -> tuple[str, str]:
        """("file" | "dir" | "missing" | "case", real name). Capitals matter on the Raspberry Pi."""

        if rel in ("", "."):
            return "dir", ""
        current = self.root
        for part in rel.split("/"):
            try:
                names = os.listdir(current)
            except OSError:
                return "missing", ""
            if part not in names:
                lowered = {name.lower(): name for name in names}
                if part.lower() in lowered:
                    return "case", lowered[part.lower()]
                return "missing", ""
            current = current / part
        return ("dir" if current.is_dir() else "file"), ""

    def _include(self, tag: HATag, rel: str, stack: tuple[str, ...]) -> Any:
        target, problem = self._target(rel, tag.text)
        if problem == "outside":
            self.findings.add("include-outside-folder", tag.file, tag.line, f'{tag.tag} {tag.text} points outside the config folder.')
            return None
        if problem or target is None:
            self.findings.add("include-missing", tag.file, tag.line, f"{tag.tag} has no file or folder name after it.")
            return None
        status, real = self.exact_status(target)
        if tag.tag == "!include":
            if posixpath.basename(target) == SECRETS_FILE:
                self.findings.add("secrets-included", tag.file, tag.line, "This line includes secrets.yaml directly.")
                return None
            if status != "file":
                self.findings.add("include-missing", tag.file, tag.line, self._missing_text(tag, status, real))
                return None
            if target in stack:
                self.findings.add("include-loop", tag.file, tag.line, f'"{rel}" includes "{target}", which leads back to "{rel}".')
                return None
            return self._load(target, stack)

        if status != "dir":
            self.findings.add("include-missing", tag.file, tag.line, self._missing_text(tag, status, real, folder=True))
            return None
        loaded: list[tuple[str, Any]] = []
        for file_rel in self._find_files(target):
            if file_rel in stack:
                self.findings.add("include-loop", tag.file, tag.line, f'"{rel}" includes the folder holding "{file_rel}", which leads back to itself.')
                continue
            loaded.append((file_rel, self._load(file_rel, stack)))

        if tag.tag == "!include_dir_list":
            out = LList()
            out.file, out.line = tag.file, tag.line
            for file_rel, data in loaded:
                if data is None:
                    continue
                out.append(data)
                out.item_lines.append(getattr(data, "line", 1))
                out.raw_items.append(None)
            return out
        if tag.tag == "!include_dir_merge_list":
            out = LList()
            out.file, out.line = tag.file, tag.line
            for file_rel, data in loaded:
                if isinstance(data, LList):
                    for index, item in enumerate(data):
                        out.append(item)
                        out.item_lines.append(data.item_line(index))
                        out.raw_items.append(data.raw_items[index] if index < len(data.raw_items) else None)
                elif data is not None and not (isinstance(data, LMap) and not data):
                    self.findings.add("include-wrong-content", file_rel, 1,
                                      f'"{file_rel}" is in a folder read with !include_dir_merge_list, but it doesn\'t contain a list, so it is ignored.')
            return out
        mapping = LMap()
        mapping.file, mapping.line = tag.file, tag.line
        for file_rel, data in loaded:
            if tag.tag == "!include_dir_named":
                stem = posixpath.splitext(posixpath.basename(file_rel))[0]
                mapping[stem] = data if data is not None else LMap()
                mapping.key_lines[stem] = getattr(data, "line", 1)
                continue
            if isinstance(data, LMap):
                for key, value in data.items():
                    if key in mapping:
                        self.findings.add("duplicate-key", file_rel, data.key_line(key),
                                          f'"{key}" is defined in more than one file in the "{target}" folder. Only the last one read is used.')
                    mapping[key] = value
                    mapping.key_lines[key] = data.key_line(key)
            elif data is not None:
                self.findings.add("include-wrong-content", file_rel, 1,
                                  f'"{file_rel}" is in a folder read with !include_dir_merge_named, but it doesn\'t contain named blocks, so it is ignored.')
        return mapping

    def _missing_text(self, tag: HATag, status: str, real: str, folder: bool = False) -> str:
        kind = "folder" if folder else "file"
        if status == "case":
            return (f'{tag.tag} {tag.text}: the {kind} exists but is called "{real}". Windows ignores the difference '
                    "between capital and small letters, but the Raspberry Pi doesn't, so Home Assistant won't find it.")
        if status == "dir" and not folder:
            return f'{tag.tag} {tag.text}: that is a folder, not a file. Use one of the !include_dir_… commands for folders.'
        if status == "file" and folder:
            return f'{tag.tag} {tag.text}: that is a file, not a folder. Use plain !include for a single file.'
        return f'{tag.tag} {tag.text}: there is no {kind} with that name.'

    def _find_files(self, dir_rel: str) -> list[str]:
        found: list[str] = []
        start = self.root / dir_rel if dir_rel not in ("", ".") else self.root
        for dirpath, dirnames, filenames in os.walk(start, topdown=True):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for name in sorted(filenames):
                if name.startswith("."):
                    continue
                rel = Path(dirpath, name).relative_to(self.root).as_posix()
                if fnmatchcase(name, "*.yaml"):
                    if name != SECRETS_FILE:
                        found.append(rel)
                elif name.lower().endswith((".yml", ".yaml")) and rel not in self.ignored_yml:
                    self.ignored_yml.add(rel)
                    self.findings.add("yml-ignored", rel, 0,
                                      f'"{rel}" is inside a folder read with an !include_dir_… command, but its name doesn\'t end in ".yaml" (small letters), so it is skipped.')
        return found

    # ------------------------------------------------------------------ secrets
    def secret_names_near(self, file_rel: str) -> set[str] | None:
        """Secret names available to a file, or None if no secrets.yaml exists on the way up."""

        names: set[str] = set()
        found = False
        directory = posixpath.dirname(file_rel)
        while True:
            if directory not in self._secret_cache:
                path = self.root / directory / SECRETS_FILE if directory else self.root / SECRETS_FILE
                self._secret_cache[directory] = scan_top_level_names(path) if path.is_file() else None
            cached = self._secret_cache[directory]
            if cached is not None:
                found = True
                names |= cached
            if not directory:
                break
            directory = posixpath.dirname(directory)
        return names if found else None

    def _check_secrets(self) -> None:
        for tag in self.secret_refs:
            names = self.secret_names_near(tag.file)
            if names is None:
                self.findings.add("secrets-file-missing", tag.file, tag.line, f"!secret {tag.text} is used, but no secrets.yaml was found.")
            elif tag.text not in names:
                self.findings.add("secret-missing", tag.file, tag.line, f'There is no entry called "{tag.text}" in secrets.yaml.')

    # ------------------------------------------------------------------ blueprints & dashboards
    def _load_blueprints(self) -> None:
        folder = self.root / "blueprints"
        if not folder.is_dir():
            return
        self._role = "blueprint"
        for dirpath, dirnames, filenames in os.walk(folder):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for name in sorted(filenames):
                if not name.endswith(".yaml") or name.startswith("."):
                    continue
                rel = Path(dirpath, name).relative_to(self.root).as_posix()
                data = self._load(rel, ())
                self.blueprints[rel[len("blueprints/"):]] = data
        self._role = "config"

    def _check_inputs(self) -> None:
        for tag, role in self.input_refs:
            if role != "blueprint":
                self.findings.add("input-outside-blueprint", tag.file, tag.line, f"!input {tag.text} is used in a file that isn't a blueprint.")

    def _load_dashboards(self) -> None:
        names: list[str] = []
        if (self.root / "ui-lovelace.yaml").is_file():
            names.append("ui-lovelace.yaml")
        lovelace = self.config.get("lovelace") if isinstance(self.config, LMap) else None
        if isinstance(lovelace, LMap) and isinstance(lovelace.get("dashboards"), LMap):
            for board in lovelace["dashboards"].values():
                if isinstance(board, LMap) and isinstance(board.get("filename"), str):
                    target, problem = self._target("configuration.yaml", board["filename"])
                    if target and not problem and self.exact_status(target)[0] == "file" and target not in names:
                        names.append(target)
        self._role = "dashboard"
        for rel in names:
            data = self._load(rel, ())
            if data is not None:
                self.dashboards.append(data)
        self._role = "config"

    def _check_ui_files(self) -> None:
        if not self.has_configuration:
            return
        for name, line in UI_FILES.items():
            if (self.root / name).is_file() and name not in self.files:
                self.findings.add("ui-file-not-included", name, 0,
                                  f'"{name}" exists but configuration.yaml doesn\'t include it. Add this line to configuration.yaml:   {line}')

    def _find_unused_files(self) -> None:
        unused: list[str] = []
        for dirpath, dirnames, filenames in os.walk(self.root, topdown=True):
            here = Path(dirpath)
            at_top = here == self.root
            dirnames[:] = sorted(
                d for d in dirnames
                if not d.startswith(".")
                and not (at_top and d in FOREIGN_DIRS)
                and not (here / d / "configuration.yaml").exists()
            )
            for name in sorted(filenames):
                if not name.lower().endswith((".yaml", ".yml")) or name.startswith("."):
                    continue
                rel = (here / name).relative_to(self.root).as_posix()
                if rel in self.files or rel in self.ignored_yml or name == SECRETS_FILE:
                    continue
                if at_top and (name in SPECIAL_FILES or name in UI_FILES):
                    continue
                unused.append(rel)
        for rel in unused:
            self.findings.add("file-not-used", rel, 0, f'Nothing includes "{rel}".')
        self.unused_files = unused

    def describe_files(self) -> str:
        return quote_list(sorted(self.files))
