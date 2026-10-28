"""Tidy mode: write a corrected COPY of the configuration files to a new folder.

Promises:

* The original folder is never changed. We only read from it.
* Only changes that are certain to mean exactly the same thing to Home
  Assistant are made (renaming old setting names to their new ones, putting
  keys in a standard order, consistent indentation).
* Every tidied file is read back with Home Assistant's own rules and compared
  with the original. If the meaning differs in any way — or a comment would be
  lost — we step back to a more cautious level, and in the end leave the file
  untouched rather than risk it.
* Everything else (anything uncertain) is only reported, never changed.
"""

from __future__ import annotations

import copy
import io
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from .doctor import Result
from .yamlio import LMap, NotUtf8, parse_yaml, read_text, to_plain

MARKER = "ABOUT-THIS-FOLDER.txt"
AUTOMATION_ORDER = [
    "id", "alias", "description", "use_blueprint", "initial_state", "trace", "variables",
    "trigger_variables", "triggers", "conditions", "actions", "mode", "max", "max_exceeded",
]
SCRIPT_ORDER = ["alias", "description", "icon", "fields", "variables", "sequence", "mode", "max", "max_exceeded"]

WHY_PLURAL = ("Home Assistant 2024.10 renamed this. The old name still works, but the new one is what the "
              "automation editor and the documentation use.")
WHY_PLATFORM = "Home Assistant 2024.10 changed triggers to start with trigger: instead of platform:."
WHY_SERVICE = "Home Assistant 2024.8 renamed service: to action:. Both work today; action: is the current way."
WHY_DATA_TEMPLATE = "Templates are allowed directly in data: (and action:), so the old _template names aren't needed."
WHY_ORDER = ("Puts the parts in the standard order the editor uses, so every automation reads the same way. "
             "The order makes no difference to Home Assistant.")
WHY_SORT = "A to Z makes them easier to find. The order makes no difference to Home Assistant."
WHY_FORMAT = ("Made the indentation and spacing consistent (2 spaces for each level, list dashes indented under their heading). "
              "This doesn't change what anything does.")
WHY_BOM = "Removed an invisible marker (a \"byte order mark\") that Windows programs sometimes put at the start of a file."
WHY_CRLF = "Changed Windows-style line endings to the plain ones the Raspberry Pi uses. Home Assistant reads both."


class OutputFolderProblem(Exception):
    pass


@dataclass
class Change:
    line: int
    what: str
    why: str


@dataclass
class FileResult:
    rel: str
    status: str  # "changed", "unchanged", "skipped"
    changes: list[Change] = field(default_factory=list)
    reason: str = ""
    note: str = ""
    new_text: str = ""


@dataclass
class TidyReport:
    out_dir: Path
    files: list[FileResult]

    @property
    def changed(self) -> list[FileResult]:
        return [f for f in self.files if f.status == "changed"]

    @property
    def skipped(self) -> list[FileResult]:
        return [f for f in self.files if f.status == "skipped"]


# ------------------------------------------------------------------ the two kinds of data we edit

class _Ops:
    """How to rename and reorder keys, for one kind of mapping object."""

    def __init__(self, line_of: Callable[[Any], int], key_line: Callable[[Any, Any], int], comments: Callable[[Any], bool]) -> None:
        self.line_of = line_of
        self.key_line = key_line
        self.has_comments = comments

    @staticmethod
    def rename(mapping: dict, old: Any, new: Any) -> None:
        if isinstance(mapping, CommentedMap):
            position = list(mapping.keys()).index(old)
            value = mapping[old]
            comment = mapping.ca.items.pop(old, None)
            del mapping[old]
            mapping.insert(position, new, value)
            if comment is not None:
                mapping.ca.items[new] = comment
        else:
            items = [(new if k == old else k, v) for k, v in mapping.items()]
            mapping.clear()
            for k, v in items:
                mapping[k] = v

    @staticmethod
    def reorder(mapping: dict, keys: list) -> bool:
        current = list(mapping.keys())
        if keys == current:
            return False
        items = [(k, mapping[k]) for k in keys]
        for k in current:
            del mapping[k]
        for k, v in items:
            mapping[k] = v
        return True


def _truthy(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, list):
        return any(_truthy(v) for v in value)
    return True


def _ruamel_has_comments(node: Any) -> bool:
    if isinstance(node, (CommentedMap, CommentedSeq)):
        ca = node.ca
        if _truthy(ca.comment) or any(_truthy(v) for v in ca.items.values()) or _truthy(getattr(ca, "end", None)):
            return True
        if isinstance(node, CommentedMap) and getattr(node, "merge", None):
            return True  # treat "<<: *anchor" as untouchable
        children = node.values() if isinstance(node, CommentedMap) else node
        return any(_ruamel_has_comments(child) for child in children)
    return False


def _ruamel_key_line(mapping: Any, key: Any) -> int:
    try:
        return mapping.lc.key(key)[0] + 1
    except Exception:
        return mapping.lc.line + 1


RUAMEL = _Ops(lambda m: m.lc.line + 1, _ruamel_key_line, _ruamel_has_comments)
PLAIN = _Ops(lambda m: getattr(m, "line", 0), lambda m, k: m.key_line(k) if isinstance(m, LMap) else 0, lambda m: False)


# ------------------------------------------------------------------ the changes themselves

@dataclass
class Targets:
    automations: set[tuple[int, frozenset]]
    scripts: set[tuple[int, frozenset]]
    collections: set[tuple[int, frozenset]]


def _iter_maps(node: Any, out: list, seen: set[int]) -> list:
    if id(node) in seen:
        return out
    seen.add(id(node))
    if isinstance(node, dict):
        out.append(node)
        for value in node.values():
            _iter_maps(value, out, seen)
    elif isinstance(node, list):
        for value in node:
            _iter_maps(value, out, seen)
    return out


def _keyset(mapping: dict) -> frozenset:
    return frozenset(str(k) for k in mapping.keys())


def _as_items(value: Any) -> list:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, dict):
        return [value]
    return []


def _trigger_maps(value: Any) -> list[dict]:
    out = []
    for item in _as_items(value):
        if isinstance(item, dict):
            if "triggers" in item and not ("trigger" in item or "platform" in item):
                out.extend(_trigger_maps(item["triggers"]))
            else:
                out.append(item)
    return out


def _step_maps(value: Any) -> list[dict]:
    out: list[dict] = []
    for step in _as_items(value):
        if not isinstance(step, dict):
            continue
        out.append(step)
        if "choose" in step:
            for option in _as_items(step.get("choose")):
                if isinstance(option, dict):
                    out.extend(_step_maps(option.get("sequence")))
            out.extend(_step_maps(step.get("default")))
        if "if" in step:
            out.extend(_step_maps(step.get("then")))
            out.extend(_step_maps(step.get("else")))
        if isinstance(step.get("repeat"), dict):
            out.extend(_step_maps(step["repeat"].get("sequence")))
        if "parallel" in step:
            for branch in _as_items(step.get("parallel")):
                if isinstance(branch, dict) and "sequence" in branch and len(branch) <= 2:
                    out.extend(_step_maps(branch.get("sequence")))
                else:
                    out.extend(_step_maps([branch]))
        if "sequence" in step and not any(k in step for k in ("action", "service", "repeat", "choose", "if")):
            out.extend(_step_maps(step.get("sequence")))
    return out


def _note(changes: list | None, ops: _Ops, mapping: dict, key: Any, what: str, why: str) -> None:
    if changes is not None:
        changes.append(Change(ops.key_line(mapping, key), what, why))


def _migrate_steps(steps: Any, ops: _Ops, changes: list | None) -> None:
    for step in _step_maps(steps):
        if "service" in step and "action" not in step and "service_template" not in step:
            _note(changes, ops, step, "service", f'Changed "service: {step["service"]}" to "action: {step["service"]}".', WHY_SERVICE)
            ops.rename(step, "service", "action")
        if "service_template" in step and "action" not in step and "service" not in step:
            _note(changes, ops, step, "service_template", 'Changed "service_template:" to "action:".', WHY_DATA_TEMPLATE)
            ops.rename(step, "service_template", "action")
        if "data_template" in step and "data" not in step:
            _note(changes, ops, step, "data_template", 'Changed "data_template:" to "data:".', WHY_DATA_TEMPLATE)
            ops.rename(step, "data_template", "data")
        if "wait_for_trigger" in step:
            _migrate_triggers(step.get("wait_for_trigger"), ops, changes)


def _migrate_triggers(value: Any, ops: _Ops, changes: list | None) -> None:
    for trigger in _trigger_maps(value):
        if "platform" in trigger and "trigger" not in trigger:
            _note(changes, ops, trigger, "platform",
                  f'Changed "platform: {trigger["platform"]}" to "trigger: {trigger["platform"]}".', WHY_PLATFORM)
            ops.rename(trigger, "platform", "trigger")


def _canonical(mapping: dict, order: list[str]) -> list:
    keys = list(mapping.keys())
    return [k for k in order if k in mapping] + [k for k in keys if k not in order]


def _migrate_automation(mapping: dict, ops: _Ops, changes: list | None, renames: bool, reorder: bool) -> None:
    if renames:
        for old, new in (("trigger", "triggers"), ("condition", "conditions"), ("action", "actions")):
            if old in mapping and new not in mapping:
                _note(changes, ops, mapping, old, f'Changed "{old}:" to "{new}:".', WHY_PLURAL)
                ops.rename(mapping, old, new)
        _migrate_triggers(mapping.get("triggers"), ops, changes)
        _migrate_steps(mapping.get("actions"), ops, changes)
    if reorder and not ops.has_comments(mapping):
        line = ops.line_of(mapping)
        if ops.reorder(mapping, _canonical(mapping, AUTOMATION_ORDER)) and changes is not None:
            name = mapping.get("alias") or mapping.get("id") or "this automation"
            changes.append(Change(line, f'Put the parts of automation "{name}" in the standard order.', WHY_ORDER))


def _migrate_script(mapping: dict, ops: _Ops, changes: list | None, renames: bool, reorder: bool) -> None:
    if renames:
        _migrate_steps(mapping.get("sequence"), ops, changes)
    if reorder and not ops.has_comments(mapping):
        line = ops.line_of(mapping)
        if ops.reorder(mapping, _canonical(mapping, SCRIPT_ORDER)) and changes is not None:
            changes.append(Change(line, f'Put the parts of script "{mapping.get("alias") or "this script"}" in the standard order.', WHY_ORDER))


def _sort_collection(mapping: dict, ops: _Ops, changes: list | None) -> None:
    if ops.has_comments(mapping) or not all(isinstance(k, str) for k in mapping):
        return
    line = ops.line_of(mapping)
    if ops.reorder(mapping, sorted(mapping.keys(), key=lambda k: k.lower())) and changes is not None:
        changes.append(Change(line, "Sorted the named items in this section A to Z.", WHY_SORT))


def apply_changes(root: Any, ops: _Ops, targets: Targets, renames: bool, reorder: bool, changes: list | None) -> None:
    plan = []
    for mapping in _iter_maps(root, [], set()):
        key = (ops.line_of(mapping), _keyset(mapping))
        if key in targets.automations:
            plan.append(("automation", mapping))
        elif key in targets.scripts:
            plan.append(("script", mapping))
        elif key in targets.collections:
            plan.append(("collection", mapping))
    for kind, mapping in plan:
        if kind == "automation":
            _migrate_automation(mapping, ops, changes, renames, reorder)
        elif kind == "script":
            _migrate_script(mapping, ops, changes, renames, reorder)
        elif reorder:
            _sort_collection(mapping, ops, changes)


# ------------------------------------------------------------------ safety checks

def _yaml() -> YAML:
    y = YAML(typ="rt")
    y.preserve_quotes = True
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def _dump(data: Any) -> str:
    buffer = io.StringIO()
    _yaml().dump(data, buffer)
    text = buffer.getvalue()
    if isinstance(data, list):  # keep "- id:" at the left edge, like Home Assistant's own files
        text = "\n".join(line[2:] if line.startswith("  ") else line for line in text.split("\n"))
    if not text.endswith("\n"):
        text += "\n"
    return text


_COMMENT = re.compile(r"(?:^|\s)#(.*)$")


def comment_texts(text: str) -> Counter:
    """Every comment's text, so we can prove none were lost."""

    found: Counter = Counter()
    for line in text.split("\n"):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            found[stripped[1:].strip()] += 1
            continue
        in_single = in_double = False
        for index, char in enumerate(line):
            if char == "'" and not in_double:
                in_single = not in_single
            elif char == '"' and not in_single:
                in_double = not in_double
            elif char == "#" and not in_single and not in_double and index > 0 and line[index - 1] in " \t":
                found[line[index + 1:].strip()] += 1
                break
    return found


ORDER_MATTERS = ("variables", "trigger_variables")


def same_meaning(a: Any, b: Any, key: Any = None) -> bool:
    """Equal in every way Home Assistant cares about (key order only matters for variables)."""

    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            return False
        if key in ORDER_MATTERS and list(a) != list(b):
            return False
        return all(same_meaning(a[k], b[k], k) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same_meaning(x, y, key) for x, y in zip(a, b))
    if type(a) is not type(b):
        if isinstance(a, bool) or isinstance(b, bool):
            return False
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return a == b
        return False
    if isinstance(a, float) and a != a:
        return b != b
    return a == b


# ------------------------------------------------------------------ one file

LEVELS = (("full", True, True), ("renames", True, False), ("format", False, False))


def _targets_for(result: Result, rel: str) -> Targets:
    model = result.model
    autos = {(a.line, _keyset(a.raw)) for a in model.automations if a.file == rel and a.raw.file == rel}
    scripts = {(s.raw.line, _keyset(s.raw)) for s in model.scripts if s.raw.file == rel}
    collections = {(m.line, _keyset(m)) for m in model.named_collections if getattr(m, "file", "") == rel}
    return Targets(autos, scripts, collections)


def tidy_text(text: str, rel: str, targets: Targets, keep_order: bool = False) -> FileResult:
    """Tidy one file's text. Returns the result and (in .note) the new text when changed."""

    original = parse_yaml(text, rel)
    if original.problem:
        return FileResult(rel, "skipped", reason="It has a layout mistake, so it can't be read safely. Fix it first (see the report).")
    if original.duplicates:
        return FileResult(rel, "skipped", reason="It has the same setting twice, so it isn't clear which one you meant. Fix it first (see the report).")
    if original.data is None:
        return FileResult(rel, "unchanged")
    if any(tag.tag not in ("!include", "!include_dir_list", "!include_dir_named", "!include_dir_merge_list",
                           "!include_dir_merge_named", "!secret", "!input", "!env_var") for tag in original.tags):
        return FileResult(rel, "skipped", reason="It uses a ! command Home Assistant doesn't know, so it was left alone.")
    lf_text = text.replace("\r\n", "\n")
    original_comments = comment_texts(lf_text)
    held_back = ""
    for name, renames, reorder in LEVELS:
        if keep_order and reorder:
            continue
        try:
            data = _yaml().load(lf_text)
        except Exception:
            return FileResult(rel, "skipped", reason="The tidying tool couldn't read it in a way that keeps comments, so it was left alone.")
        if data is None:
            return FileResult(rel, "unchanged")
        changes: list[Change] = []
        apply_changes(data, RUAMEL, targets, renames, reorder, changes)
        try:
            new_text = _dump(data)
        except Exception:
            held_back = "The tidying tool couldn't write it back safely."
            continue
        expected = copy.deepcopy(original.data)
        apply_changes(expected, PLAIN, targets, renames, reorder, None)
        reread = parse_yaml(new_text, rel)
        if reread.problem or reread.duplicates or not same_meaning(to_plain(expected), to_plain(reread.data)):
            held_back = "Tidying would have changed what it means, so the cautious choice was made."
            continue
        if comment_texts(new_text) != original_comments:
            held_back = "Tidying would have lost or moved a comment, so the cautious choice was made."
            continue
        result = FileResult(rel, "changed" if new_text != text else "unchanged", sorted(changes, key=lambda c: c.line))
        if name != "full" and not keep_order:
            result.note = "Key order left as it was" + (f" ({held_back[0].lower() + held_back[1:]})" if held_back else "") + "."
        result.new_text = new_text
        return result
    return FileResult(rel, "skipped", reason=held_back or "It couldn't be tidied safely, so it was left exactly as it is.")


def _describe_formatting(text: str, new_text: str, rel: str, targets: Targets, result: FileResult) -> None:
    lf_text = text.replace("\r\n", "\n")
    formatted = tidy_text(lf_text, rel, Targets(set(), set(), set()))
    plain_format = formatted.new_text if formatted.status in ("changed", "unchanged") else lf_text
    if plain_format != lf_text:
        result.changes.insert(0, Change(0, "Made the layout consistent.", WHY_FORMAT))
    if "\r\n" in text:
        result.changes.insert(0, Change(0, "Changed the line endings.", WHY_CRLF))


# ------------------------------------------------------------------ the whole folder

def check_output_folder(root: Path, out_dir: Path) -> Path:
    root = Path(root).resolve()
    out = Path(out_dir).resolve()
    if out == root or root in out.parents:
        raise OutputFolderProblem(
            "The tidied copy can't go inside your configuration folder (that would mix the copy with the originals). "
            "Choose a folder somewhere else, for example next to it.")
    if out in root.parents:
        raise OutputFolderProblem("The tidied copy can't go in a folder that contains your configuration folder. Choose a new, empty folder.")
    if out.exists():
        if not out.is_dir():
            raise OutputFolderProblem(f'"{out.name}" already exists and is a file, not a folder.')
        contents = [p for p in out.iterdir()]
        if contents and not (out / MARKER).exists():
            raise OutputFolderProblem(
                f'The folder "{out.name}" already has things in it. To be safe, the doctor only writes into a new or empty folder '
                "(or one it made itself before).")
    return out


def tidy(result: Result, out_dir: Path, keep_order: bool = False) -> TidyReport:
    out = check_output_folder(result.root, out_dir)
    files: list[FileResult] = []
    for rel, source in sorted(result.config.files.items()):
        if source.role == "dashboard":
            continue
        if source.role == "blueprint":
            data = source.parsed.data
            if isinstance(data, dict) and isinstance(data.get("blueprint"), dict) and data["blueprint"].get("source_url"):
                files.append(FileResult(rel, "skipped", reason="This blueprint was downloaded from the internet; update it from where it came from instead."))
                continue
        path = result.root / rel
        try:
            raw = path.read_bytes()
            text = read_text(path)
        except (OSError, NotUtf8):
            files.append(FileResult(rel, "skipped", reason="It couldn't be read as text."))
            continue
        targets = _targets_for(result, rel)
        try:
            outcome = tidy_text(text, rel, targets, keep_order)
        except Exception:  # pragma: no cover - a bug in the doctor must never damage a copy
            outcome = FileResult(rel, "skipped", reason="Something unexpected happened while tidying it, so it was left alone.")
        if outcome.status == "skipped":
            files.append(outcome)
            continue
        new_text = outcome.new_text
        if raw.startswith(b"\xef\xbb\xbf"):
            outcome.changes.insert(0, Change(0, "Removed the byte order mark.", WHY_BOM))
            outcome.status = "changed"
        if outcome.status == "changed":
            _describe_formatting(text, new_text, rel, targets, outcome)
            target = out / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(new_text.encode("utf-8"))
        files.append(outcome)
    out.mkdir(parents=True, exist_ok=True)
    (out / MARKER).write_bytes(
        ("This folder was made by ha-config-doctor's tidy mode.\n"
         "It holds tidied COPIES of some of your Home Assistant files. Your original folder was not changed.\n"
         "Read CHANGES.html (or CHANGES.md) to see what changed in each file and why.\n"
         "secrets.yaml is never copied here. Keep this folder private, just like your original configuration.\n").encode("utf-8"))
    return TidyReport(out, files)
