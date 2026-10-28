"""File-level checks: passwords typed into files, blueprints, and old trigger syntax in template sections.

Removed and retired features are checked in retired.py, from the rules in data/ha_rules.yaml.
"""

from __future__ import annotations

from typing import Any

from ..redact import is_sensitive_key
from ..util import as_list, is_template
from ..yamlio import HATag, LList, LMap
from .common import Ctx

# Settings whose values are secrets (not merely personal), so typing them into a file is risky.
_SECRET_WORDS = ("password", "passwd", "token", "api_key", "apikey", "secret", "private_key")


def _is_secret_setting(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    name = key.lower()
    if name in ("pin", "code", "key", "encryption_key", "network_key", "psk"):
        return True
    return is_sensitive_key(name) and any(word in name for word in _SECRET_WORDS)


def run(ctx: Ctx) -> None:
    _inline_secrets(ctx, ctx.cs.config)
    _blueprint_files(ctx)
    _template_section_old_syntax(ctx)


# ------------------------------------------------------------------ passwords typed into files

def _inline_secrets(ctx: Ctx, value: Any, seen: set[int] | None = None) -> None:
    seen = seen if seen is not None else set()
    if id(value) in seen:
        return
    seen.add(id(value))
    if isinstance(value, LMap):
        for key, item in value.items():
            if _is_secret_setting(key) and isinstance(item, (str, int)) and not isinstance(item, bool):
                text = str(item)
                if text and not is_template(text) and not text.startswith("!"):
                    if str(key).lower() == "code" and isinstance(item, str) and not text.isdigit():
                        continue  # e.g. "code: 'arm_home'" style settings that aren't PIN codes
                    ctx.add("inline-secret", value.file, value.key_line(key),
                            f'The "{key}" setting has its value typed directly into the file (the value is hidden here).')
            elif isinstance(item, (LMap, LList)):
                _inline_secrets(ctx, item, seen)
    elif isinstance(value, LList):
        for item in value:
            if isinstance(item, (LMap, LList)):
                _inline_secrets(ctx, item, seen)


# ------------------------------------------------------------------ blueprint files

def _collect_inputs(value: Any, out: list[HATag]) -> None:
    if isinstance(value, HATag) and value.tag == "!input":
        out.append(value)
    elif isinstance(value, dict):
        for item in value.values():
            _collect_inputs(item, out)
    elif isinstance(value, list):
        for item in value:
            _collect_inputs(item, out)


def _blueprint_files(ctx: Ctx) -> None:
    from .automations import _blueprint_inputs

    for rel, data in ctx.cs.blueprints.items():
        if not isinstance(data, LMap) or not isinstance(data.get("blueprint"), LMap):
            continue
        declared = _blueprint_inputs(data["blueprint"].get("input"))
        used: list[HATag] = []
        _collect_inputs({k: v for k, v in data.items() if k != "blueprint"}, used)
        used_names = {str(tag.value) for tag in used}
        for tag in used:
            if str(tag.value) not in declared:
                ctx.add("blueprint-input-undeclared", tag.file, tag.line,
                        f'!input {tag.value} is used but "{tag.value}" isn\'t listed under blueprint: input:.', f'Blueprint "{rel}"')
        spec = data["blueprint"].get("input")
        for name in declared:
            if name not in used_names:
                line = spec.key_line(name) if isinstance(spec, LMap) and name in spec else data["blueprint"].line
                ctx.add("blueprint-input-unused", f"blueprints/{rel}", line,
                        f'The setting "{name}" is never used with !input.', f'Blueprint "{rel}"')


def _template_section_old_syntax(ctx: Ctx) -> None:
    for section in ctx.model.section_list("template"):
        for block in as_list(section.value):
            if not isinstance(block, LMap):
                continue
            for key in ("trigger", "triggers"):
                for trigger in as_list(block.get(key)):
                    if isinstance(trigger, LMap) and "platform" in trigger and "trigger" not in trigger:
                        ctx.add("old-platform-key", trigger.file, trigger.key_line("platform"),
                                f'Uses "platform: {trigger.get("platform")}" in a trigger-based template.', '"template:" section',
                                fix="Rename platform: to trigger: by hand (tidy mode leaves the template: section alone to be safe).")
