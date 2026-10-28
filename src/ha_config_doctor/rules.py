"""Rules about removed, retired and changed Home Assistant features, read from data/ha_rules.yaml.

Nothing about which version removed what is written into the program: it all comes
from the data file, so it can be corrected without changing any code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .catalog import ERROR, TIDY, WARNING
from .util import slugify
from .yamlio import to_plain

RULES_FILE = "ha_rules.yaml"
KINDS = {
    "integration", "platform", "option", "platform_option", "automation_option", "action",
    "action_data", "template_attribute", "changed", "legacy_template",
}
VERIFICATION = {"verified", "unverified"}
BASIS = {"owner", "search-summary", "author-memory"}
BASIS_TEXT = {
    "owner": "based on information from the owner of this set-up",
    "search-summary": "based on a web-search summary of Home Assistant's release notes and community posts",
    "author-memory": "based on the tool author's own knowledge",
}
_VERSION = re.compile(r"^\s*(\d{4})\.(\d{1,2})(?:\.(\d+))?")


class RulesProblem(Exception):
    """The rules file is missing or written wrongly."""


def parse_version(text: Any) -> tuple[int, int, int] | None:
    """(2026, 10, 4) for "2026.10.4"; beta and development suffixes are ignored."""

    if text is None:
        return None
    match = _VERSION.match(str(text))
    if not match:
        return None
    year, month, patch = int(match.group(1)), int(match.group(2)), int(match.group(3) or 0)
    if not 1 <= month <= 12:
        return None
    return (year, month, patch)


def version_text(parts: tuple[int, int, int]) -> str:
    return f"{parts[0]}.{parts[1]}" + (f".{parts[2]}" if parts[2] else "")


@dataclass
class Rule:
    id: str
    kind: str
    match: dict
    explanation: str
    fix: str
    source: str
    as_of: str
    verification: str
    basis: str
    deprecated_in: str | None = None
    removed_in: str | None = None
    changed_in: str | None = None
    planned_removal: str | None = None
    fix_if_older_than: dict | None = None
    basis_note: str = ""

    @property
    def verified(self) -> bool:
        return self.verification == "verified"

    def provenance(self) -> str:
        if self.verified:
            return f"Checked against the official Home Assistant notes on {self.as_of}."
        return f"Not yet checked against the official Home Assistant release notes ({BASIS_TEXT[self.basis]}; reviewed {self.as_of})."


@dataclass
class Verdict:
    status: str  # removed, deprecated, changed or future
    severity: str
    when: str  # a plain sentence about the versions


@dataclass
class RuleBook:
    rules: list[Rule]
    as_of: str
    newest_release_known: tuple[int, int, int]
    verification_status: str
    still_supported: list[dict] = field(default_factory=list)
    conversion: dict = field(default_factory=dict)
    leads: list[str] = field(default_factory=list)
    path: Path | None = None

    @property
    def unverified(self) -> list[Rule]:
        return [r for r in self.rules if not r.verified]

    def by_id(self, rule_id: str) -> Rule:
        return next(r for r in self.rules if r.id == rule_id)


@dataclass
class HAVersion:
    parts: tuple[int, int, int]
    text: str
    source: str  # "file" (.HA_VERSION), "option" (--ha-version) or "assumed"
    newer_than_rules: bool = False


# ------------------------------------------------------------------ loading

def default_rules_path() -> Path:
    """The rules file: inside the installed package, or data/ in a copy of the source."""

    candidates = []
    try:
        from importlib import resources

        candidates.append(Path(str(resources.files("ha_config_doctor.data").joinpath(RULES_FILE))))
    except (ModuleNotFoundError, TypeError, AttributeError):
        pass
    candidates.append(Path(__file__).resolve().parents[2] / "data" / RULES_FILE)
    for path in candidates:
        if path.is_file():
            return path
    raise RulesProblem("The rules file (data/ha_rules.yaml) is missing from this copy of ha-config-doctor. Please reinstall it.")


def _version_field(rule: dict, key: str, rule_id: str) -> str | None:
    value = rule.get(key)
    if value is None:
        return None
    if parse_version(value) is None:
        raise RulesProblem(f'Rule "{rule_id}": {key} "{value}" isn\'t a version like 2026.6.')
    return str(value)


def load_rules(path: Path | None = None) -> RuleBook:
    path = Path(path) if path else default_rules_path()
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        stamp = 0
    return _load_rules(str(path), stamp)


@lru_cache(maxsize=8)
def _load_rules(path_text: str, _stamp: int) -> RuleBook:
    path = Path(path_text)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as err:
        raise RulesProblem(f"The rules file {path.name} couldn't be read ({type(err).__name__}).") from err
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        raise RulesProblem(f"The rules file {path.name} has no list of rules.")
    newest = parse_version(data.get("newest_release_known"))
    if newest is None:
        raise RulesProblem("The rules file needs newest_release_known, such as 2026.10.")
    rules: list[Rule] = []
    seen: set[str] = set()
    for raw in data["rules"]:
        if not isinstance(raw, dict) or not raw.get("id"):
            raise RulesProblem("Every rule needs an id.")
        rule_id = str(raw["id"])
        if rule_id in seen:
            raise RulesProblem(f'The rule id "{rule_id}" is used twice.')
        seen.add(rule_id)
        missing = [k for k in ("kind", "match", "explanation", "fix", "source", "as_of", "verification", "basis") if not raw.get(k)]
        if missing:
            raise RulesProblem(f'Rule "{rule_id}" is missing: {", ".join(missing)}.')
        if raw["kind"] not in KINDS:
            raise RulesProblem(f'Rule "{rule_id}" has an unknown kind "{raw["kind"]}".')
        if raw["verification"] not in VERIFICATION:
            raise RulesProblem(f'Rule "{rule_id}": verification must be "verified" or "unverified".')
        if raw["basis"] not in BASIS:
            raise RulesProblem(f'Rule "{rule_id}": basis must be one of {", ".join(sorted(BASIS))}.')
        if not str(raw["source"]).startswith("https://"):
            raise RulesProblem(f'Rule "{rule_id}": source must be a web address.')
        rule = Rule(
            id=rule_id, kind=raw["kind"], match=dict(raw["match"]),
            explanation=" ".join(str(raw["explanation"]).split()), fix=" ".join(str(raw["fix"]).split()),
            source=str(raw["source"]), as_of=str(raw["as_of"]), verification=raw["verification"], basis=raw["basis"],
            deprecated_in=_version_field(raw, "deprecated_in", rule_id), removed_in=_version_field(raw, "removed_in", rule_id),
            changed_in=_version_field(raw, "changed_in", rule_id), planned_removal=_version_field(raw, "planned_removal", rule_id),
            fix_if_older_than=raw.get("fix_if_older_than"), basis_note=" ".join(str(raw.get("basis_note") or "").split()),
        )
        if rule.kind == "changed" and not rule.changed_in:
            raise RulesProblem(f'Rule "{rule_id}" is a behaviour change, so it needs changed_in.')
        if rule.kind != "changed" and not (rule.deprecated_in or rule.removed_in or rule.planned_removal):
            raise RulesProblem(f'Rule "{rule_id}" needs deprecated_in, removed_in or planned_removal.')
        rules.append(rule)
    return RuleBook(
        rules=rules, as_of=str(data.get("as_of", "")), newest_release_known=newest,
        verification_status=" ".join(str(data.get("verification_status", "")).split()),
        still_supported=list(data.get("still_supported") or []), conversion=dict(data.get("legacy_template_conversion") or {}),
        leads=[str(x) for x in data.get("leads") or []], path=path,
    )


# ------------------------------------------------------------------ which version, and what it means

def ha_version_for(root: Path, override: str | None, book: RuleBook) -> HAVersion:
    """The version given with --ha-version, else the one in .HA_VERSION, else the newest the rules know."""

    if override:
        parts = parse_version(override)
        if parts is None:
            raise RulesProblem(f'"{override}" isn\'t a Home Assistant version. Write it like 2026.10.4.')
        info = HAVersion(parts, str(override).strip(), "option")
    else:
        info = None
        version_file = Path(root) / ".HA_VERSION"
        if version_file.is_file():
            try:
                text = version_file.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                text = ""
            parts = parse_version(text)
            if parts:
                info = HAVersion(parts, text[:40], "file")
        if info is None:
            info = HAVersion(book.newest_release_known, version_text(book.newest_release_known), "assumed")
    info.newer_than_rules = info.parts[:2] > book.newest_release_known[:2]
    return info


def judge(rule: Rule, version: tuple[int, int, int]) -> Verdict:
    you = f"this set-up runs {version_text(version)}"
    if rule.kind == "changed":
        changed = parse_version(rule.changed_in)
        if version >= changed:  # type: ignore[operator]
            return Verdict("changed", WARNING, f"Changed in Home Assistant {rule.changed_in} ({you}).")
        return Verdict("future", TIDY, f"This changes in Home Assistant {rule.changed_in}; {you}, so it doesn't affect you yet.")
    deprecated = parse_version(rule.deprecated_in)
    removed = parse_version(rule.removed_in)
    if removed and version >= removed:
        earlier = f", after being marked for retirement in {rule.deprecated_in}" if rule.deprecated_in else ""
        return Verdict("removed", ERROR, f"Removed in Home Assistant {rule.removed_in}{earlier} ({you}).")
    if deprecated and version >= deprecated:
        later = rule.removed_in or rule.planned_removal
        due = f"; due to be removed in {later}" if later else ""
        return Verdict("deprecated", WARNING, f"Marked for retirement in Home Assistant {rule.deprecated_in}{due} ({you}).")
    if deprecated:
        return Verdict("future", TIDY, f"Due to be marked for retirement in Home Assistant {rule.deprecated_in}; {you}, so it still works for now.")
    target = rule.removed_in or rule.planned_removal
    return Verdict("future", TIDY, f"Due to be removed in Home Assistant {target}; {you}, so it still works for now.")


def fix_for(rule: Rule, version: tuple[int, int, int]) -> str:
    older = rule.fix_if_older_than
    if isinstance(older, dict) and parse_version(older.get("version")) and version < parse_version(older.get("version")):  # type: ignore[operator]
        return " ".join(str(older.get("text", rule.fix)).split())
    return rule.fix


# ------------------------------------------------------------------ old template entities, written the new way

class _Dumper(yaml.SafeDumper):
    def increase_indent(self, flow: bool = False, indentless: bool = False) -> Any:  # lists indented under their key
        return super().increase_indent(flow, False)


def _represent_str(dumper: yaml.SafeDumper, data: str) -> yaml.Node:
    if "\n" in data:
        style = "|"
    elif "{{" in data or "{%" in data:
        style = '"'  # templates read best in double quotes, as in Home Assistant's own examples
    else:
        style = None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


def _represent_tag(dumper: yaml.SafeDumper, data: tuple) -> yaml.Node:
    if len(data) == 3 and data[0] == "tag":
        return dumper.represent_scalar(data[1], str(data[2]))
    return dumper.represent_list(list(data))


_Dumper.add_representer(str, _represent_str)
_Dumper.add_representer(tuple, _represent_tag)
FIRST_KEYS = ("name", "unique_id", "default_entity_id", "state")


def legacy_template_replacement(domain: str, entry: dict, conversion: dict) -> str:
    """A suggested template: section replacing one old "platform: template" block."""

    plain = to_plain(entry)
    plural = (conversion.get("plural_keys") or {}).get(domain)
    mapping = dict(conversion.get("common") or {})
    mapping.update((conversion.get("by_domain") or {}).get(domain) or {})
    dropped = set(conversion.get("dropped") or [])
    if plural and isinstance(plain.get(plural), dict):
        entities = [(str(key), cfg if isinstance(cfg, dict) else {}) for key, cfg in plain[plural].items()]
    else:
        single = {k: v for k, v in plain.items() if k != "platform"}
        name = single.get("name")
        entities = [(slugify(name) if isinstance(name, str) else "", single)]
    modern = []
    for object_id, cfg in entities:
        converted: dict = {}
        for key, value in cfg.items():
            if key in dropped:
                continue
            converted.setdefault(mapping.get(key, key), value)
        if object_id:
            converted["default_entity_id"] = f"{domain}.{object_id}"
        ordered = {k: converted[k] for k in FIRST_KEYS if k in converted}
        ordered.update({k: v for k, v in converted.items() if k not in ordered})
        modern.append(ordered)
    header = (f"# Suggested replacement for the old {domain} block. Check the option names against the\n"
              f"# Template documentation before using it: {conversion.get('source', 'https://www.home-assistant.io/integrations/template/')}\n")
    return header + yaml.dump({"template": [{domain: modern}]}, Dumper=_Dumper, sort_keys=False, allow_unicode=True,
                              default_flow_style=False, width=4096)
