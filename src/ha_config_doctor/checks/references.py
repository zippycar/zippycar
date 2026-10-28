"""Cross-check every entity name against Home Assistant's own records (read-only).

Uses ``.storage/core.entity_registry`` (the list of entities),
``.storage/core.device_registry`` (devices), ``.storage/core.restore_state``
(recently seen states) and the names defined in your YAML files.
"""

from __future__ import annotations

import difflib

from ..catalog import ERROR, TIDY, WARNING
from ..util import HELPER_DOMAINS, is_entity_id
from .common import Ctx

ROLE_TEXT = {
    "trigger": " It is used as a trigger, so this automation can never be started by it.",
    "condition": " It is used in a condition, which will therefore never pass as expected.",
    "action": "",
    "other": "",
}


def entity_status(ctx: Ctx, entity_id: str) -> tuple[str, str]:
    """(status, extra) where status is ok, retired, disabled, device-disabled, deleted, orphaned, orphaned-device, missing, unsure."""

    reg, model = ctx.reg, ctx.model
    retired = model.retired_defined.get(entity_id)
    if retired is not None and entity_id not in model.defined:
        definition, rule = retired
        return "retired", (f"{entity_id} was defined in {definition.file}, line {definition.line}, in a way that "
                           f"Home Assistant {rule.removed_in} stopped supporting, so it doesn't exist any more.")
    entity = reg.entities.get(entity_id)
    if entity is not None:
        if entity.disabled_by:
            return "disabled", str(entity.disabled_by)
        if entity.device_id and reg.has_devices:
            if entity.device_id in reg.deleted_devices or entity.device_id not in (reg.devices or {}):
                return "orphaned-device", ""
            if (reg.devices or {}).get(entity.device_id):
                return "device-disabled", ""
        return "ok", ""
    if entity_id in model.defined or (reg.restore is not None and entity_id in reg.restore):
        return "ok", ""
    if entity_id in reg.deleted:
        return ("orphaned" if reg.deleted[entity_id] else "deleted"), ""
    domain = entity_id.split(".", 1)[0]
    if domain in ("script", "scene", "shell_command", "rest_command"):
        return "missing", ""  # these only ever come from your YAML files
    if domain in HELPER_DOMAINS and (reg.has_entities or domain in reg.helper_ids):
        return "missing", ""
    if not reg.has_entities or domain in model.unpredictable_domains:
        return "unsure", ""
    return "missing", ""


def did_you_mean(ctx: Ctx, entity_id: str) -> str:
    domain = entity_id.split(".", 1)[0]
    candidates = [e for e in ctx.model.all_known_entities()
                  if e.startswith(domain + ".") and e != entity_id and entity_status(ctx, e)[0] == "ok"]
    match = difflib.get_close_matches(entity_id, candidates, n=1, cutoff=0.75)
    return f' Did you mean "{match[0]}"?' if match else ""


def run(ctx: Ctx) -> None:
    reg = ctx.reg
    seen: set[tuple[str, str, int]] = set()
    referenced: set[str] = set(reg.dashboard_mentions)
    for ref in ctx.model.refs:
        entity_id = ref.entity_id
        if ref.kind == "registry-id":
            mapped = reg.entity_for_registry_id(entity_id)
            if mapped is None:
                if reg.has_entities:
                    ctx.add("unknown-entity", ref.file, ref.line,
                            "This device automation step points at an entity record that no longer exists (usually after a device was re-added).",
                            ref.owner, fix="Open the automation in the editor and choose the entity again.")
                continue
            entity_id = mapped
        referenced.add(entity_id)
        if ref.kind == "dashboard":
            continue
        key = (entity_id, ref.file, ref.line)
        if key in seen:
            continue
        seen.add(key)
        if ref.kind != "template" and not is_entity_id(entity_id):
            if ref.kind in ("entity", "zone", "scene", "script-call", "customize"):
                ctx.add("invalid-entity-id", ref.file, ref.line,
                        f'"{entity_id}" isn\'t a valid entity name.' + (" Entity names are always in small letters." if entity_id.lower() != entity_id else ""),
                        ref.owner)
            continue
        status, extra = entity_status(ctx, entity_id)
        role = ROLE_TEXT.get(ref.role, "")
        if status == "retired":
            if ref.kind != "template":  # templates are reported by the template checks
                ctx.add("unknown-entity", ref.file, ref.line, extra + role, ref.owner,
                        fix="Rewrite its definition the current way (see the matching finding about it), keeping the same name.")
        elif status == "disabled":
            ctx.add("disabled-entity", ref.file, ref.line,
                    f"{entity_id} is disabled" + (f" (disabled by: {extra})" if extra else "") + "." + role, ref.owner)
        elif status == "device-disabled":
            ctx.add("disabled-entity", ref.file, ref.line, f"The device that {entity_id} belongs to is disabled." + role, ref.owner)
        elif status == "deleted":
            ctx.add("deleted-entity", ref.file, ref.line, f"{entity_id} was deleted.{did_you_mean(ctx, entity_id)}" + role, ref.owner)
        elif status in ("orphaned", "orphaned-device"):
            what = "an integration" if status == "orphaned" else "a device"
            ctx.add("orphaned-entity", ref.file, ref.line,
                    f"{entity_id} belonged to {what} that has been removed.{did_you_mean(ctx, entity_id)}" + role, ref.owner)
        elif status in ("missing", "unsure"):
            if ref.kind == "template":
                continue  # reported by the template checks with more detail
            _missing(ctx, ref, entity_id, status, role)
    for device in ctx.model.device_refs:
        if reg.has_devices and device.device_id not in (reg.devices or {}):
            ctx.add("unknown-device", device.file, device.line,
                    f"The device with id {device.device_id[:8]}… isn't in Home Assistant's list of devices.", device.owner)
    for service in ctx.model.service_refs:
        domain = service.name.split(".", 1)[0]
        if domain in ("shell_command", "rest_command", "python_script") and service.name not in ctx.model.services:
            ctx.add("missing-service", service.file, service.line,
                    f'"{service.name}" isn\'t defined in your files.', service.owner)
    _unused_helpers(ctx, referenced)


def _missing(ctx: Ctx, ref, entity_id: str, status: str, role: str) -> None:
    domain = entity_id.split(".", 1)[0]
    hint = did_you_mean(ctx, entity_id)
    if domain == "script":
        ctx.add("missing-script", ref.file, ref.line, f"There is no script called {entity_id}.{hint}", ref.owner)
    elif domain == "scene":
        ctx.add("missing-scene", ref.file, ref.line, f"There is no scene called {entity_id}.{hint}", ref.owner)
    elif domain in HELPER_DOMAINS:
        if status == "unsure":
            ctx.add("missing-helper", ref.file, ref.line,
                    f"{entity_id} isn't defined in your YAML files. It may have been made in the Home Assistant screens — copy the .storage folder too for a definite answer.{hint}",
                    ref.owner, severity=WARNING)
        else:
            ctx.add("missing-helper", ref.file, ref.line, f"There is no helper called {entity_id}.{hint}" + role, ref.owner)
    elif status == "unsure":
        return  # without Home Assistant's entity list we can't be sure, so we say nothing
    elif domain == "automation":
        ctx.add("missing-automation", ref.file, ref.line, f"There is no automation entity called {entity_id}.{hint}", ref.owner)
    elif ref.kind == "customize":
        ctx.add("unknown-entity", ref.file, ref.line,
                f"customize: has settings for {entity_id}, which doesn't exist.{hint}", ref.owner, severity=TIDY,
                fix="Remove the leftover customize entry.")
    else:
        ctx.add("unknown-entity", ref.file, ref.line, f"There is no entity called {entity_id}.{hint}" + role, ref.owner,
                severity=WARNING if ref.kind == "string" else ERROR)


def _unused_helpers(ctx: Ctx, referenced: set[str]) -> None:
    for entity_id, definition in sorted(ctx.model.helpers.items()):
        if entity_id in referenced:
            continue
        if definition.how == "yaml":
            ctx.add("unused-helper", definition.file, definition.line, f"{entity_id} isn't used anywhere the doctor could see.", "")
        else:
            ctx.add("unused-helper", "", 0, f"{entity_id} (made in the Home Assistant screens) isn't used anywhere the doctor could see.", "")
