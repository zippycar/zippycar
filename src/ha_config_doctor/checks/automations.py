"""Checks on each automation and script: structure, old syntax, timing, and things that can never happen."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from ..catalog import ERROR, WARNING
from ..model import Automation, Script
from ..util import (
    HELPER_DOMAINS, NON_NUMERIC_DOMAINS, REGISTRY_ID_RE, as_list, duration_seconds, entity_ids_in,
    human_duration, is_entity_id, is_template, parse_clock, quote_list,
)
from ..yamlio import HATag, LList, LMap
from .common import (
    AUTOMATION_KEYS, CONDITION_TYPES, MAX_EXCEEDED, SCRIPT_MODES, TRIGGER_TYPES,
    WAIT_KINDS, Ctx, all_conditions, all_triggers, chatty_reason, condition_type, file, is_disabled,
    iter_step_lists, iter_steps, line, raw, signature, step_effects, opposite, suggest,
    trigger_type,
)

UNAVAILABLE = {"unavailable", "unknown"}
NEVER_UNAVAILABLE_DOMAINS = set(HELPER_DOMAINS) | {"automation", "script", "scene", "sun", "zone", "group"}
WEEKDAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}


def run(ctx: Ctx) -> None:
    _identity(ctx)
    for automation in ctx.model.automations:
        _structure(ctx, automation)
        if automation.blueprint is not None:
            _blueprint_use(ctx, automation)
            continue
        _old_syntax(ctx, automation)
        _triggers(ctx, automation)
        _mode_and_waits(ctx, automation)
        _never_fires(ctx, automation)
        _size(ctx, automation)
    for script in ctx.model.scripts:
        _script_structure(ctx, script)
        _old_syntax(ctx, script)
        for trigger, container, index, _ in all_triggers(script):
            _check_trigger(ctx, script, trigger, container, index)
        _size(ctx, script)
    for owner in list(ctx.model.automations) + list(ctx.model.scripts):
        if isinstance(owner, Automation) and owner.blueprint is not None:
            continue
        _conditions(ctx, owner)
        _steps(ctx, owner)
    _similar_automations(ctx)
    _repeated_steps(ctx)


# ------------------------------------------------------------------ identity

def _identity(ctx: Ctx) -> None:
    by_id: dict[str, list[Any]] = defaultdict(list)
    by_alias: dict[str, list[Automation]] = defaultdict(list)
    for automation in ctx.model.automations:
        if automation.id is not None:
            by_id[automation.id].append(automation)
        else:
            ctx.add("missing-id", automation.file, automation.line,
                    f"{automation.where} has no id: line.", automation.where)
        if automation.alias:
            by_alias[automation.alias.strip().lower()].append(automation)
        else:
            ctx.add("missing-alias", automation.file, automation.line,
                    f"{automation.where} has no alias: line.", automation.where)
    for scene in ctx.model.scenes:
        if scene.get("id") is not None:
            by_id[f"scene:{scene.get('id')}"].append(scene)
    for key, items in by_id.items():
        for other in items[1:]:
            first = items[0]
            shown = key.split(":", 1)[1] if key.startswith("scene:") else key
            what = "scene" if key.startswith("scene:") else "automation"
            ctx.add("duplicate-id", other.file, other.key_line("id"),
                    f'The id "{shown}" is also used by another {what} ({first.file}, line {first.line}).',
                    other.where if isinstance(other, Automation) else f'Scene "{other.get("name", shown)}"')
    for items in by_alias.values():
        for other in items[1:]:
            first = items[0]
            ctx.add("duplicate-alias", other.file, other.key_line("alias"),
                    f'The name "{other.alias}" is also used by the automation at {first.file}, line {first.line}.', other.where)


# ------------------------------------------------------------------ structure

def _structure(ctx: Ctx, a: Automation) -> None:
    raw_map = a.raw
    retired_keys = {str(option) for rule in ctx.rules.rules if rule.kind == "automation_option"
                    for option in as_list(rule.match.get("options"))}
    for key in raw_map:
        if key in retired_keys:
            continue  # reported by the rules in data/ha_rules.yaml instead
        if key not in AUTOMATION_KEYS:
            ctx.add("unknown-automation-key", a.file, raw_map.key_line(key),
                    f'"{key}" isn\'t a setting automations have.{suggest(key, AUTOMATION_KEYS)}', a.where)
    for old, new in (("trigger", "triggers"), ("condition", "conditions"), ("action", "actions")):
        if old in raw_map and new in raw_map:
            ctx.add("both-old-and-new-keys", a.file, raw_map.key_line(old),
                    f'Both "{old}:" (line {raw_map.key_line(old)}) and "{new}:" (line {raw_map.key_line(new)}) are present.', a.where)
    if a.blueprint is None:
        triggers = [t for t in a.triggers if t is not None]
        if not triggers:
            ctx.add("no-triggers", a.file, a.line, f"{a.where} has no triggers, so it never starts by itself.", a.where)
        if not [s for s in a.actions if s is not None]:
            ctx.add("no-actions", a.file, a.line, f"{a.where} has no actions.", a.where)
    _mode_settings(ctx, a, raw_map)
    initial = raw_map.get("initial_state")
    if initial is False or (isinstance(initial, str) and initial.lower() in ("false", "off")):
        ctx.add("initial-state-off", a.file, raw_map.key_line("initial_state"),
                f"{a.where} has initial_state: false, so it is switched off every time Home Assistant starts.", a.where)
    restore = ctx.reg.restore
    if restore is not None and a.entity_id and restore.get(a.entity_id) == "off":
        ctx.add("automation-switched-off", a.file, a.line,
                f"{a.where} ({a.entity_id}) was switched off when Home Assistant last saved its state.", a.where)


def _mode_settings(ctx: Ctx, owner: Automation | Script, raw_map: LMap) -> None:
    mode = raw_map.get("mode")
    if mode is not None and (not isinstance(mode, str) or mode not in SCRIPT_MODES):
        ctx.add("invalid-mode", owner.file, raw_map.key_line("mode"),
                f'mode: {mode} isn\'t valid. Use single, restart, queued or parallel.{suggest(mode, SCRIPT_MODES)}', owner.where)
    if "max" in raw_map and owner.mode in ("single", "restart"):
        ctx.add("max-ignored", owner.file, raw_map.key_line("max"),
                f"max: is set, but mode is {owner.mode}, so it has no effect.", owner.where)
    level = raw_map.get("max_exceeded")
    if level is not None and str(level).lower() not in MAX_EXCEEDED:
        ctx.add("invalid-mode", owner.file, raw_map.key_line("max_exceeded"),
                f'max_exceeded: {level} isn\'t valid. Use silent, warning, error, info, debug or critical.', owner.where)


def _script_structure(ctx: Ctx, s: Script) -> None:
    if "sequence" not in s.raw or not as_list(s.raw.get("sequence")):
        ctx.add("script-no-sequence", s.file, s.line, f"{s.where} has no sequence: of steps.", s.where)
    if not is_entity_id(f"script.{s.key}"):
        ctx.add("invalid-entity-id", s.file, s.line,
                f'The script name "{s.key}" must use only small letters, numbers and _ (no spaces or capitals).', s.where)
    _mode_settings(ctx, s, s.raw)


# ------------------------------------------------------------------ blueprints

def _blueprint_inputs(spec: Any) -> dict[str, bool]:
    """{input name: required} — flattening input sections."""

    out: dict[str, bool] = {}
    if not isinstance(spec, LMap):
        return out
    for name, item in spec.items():
        if isinstance(item, LMap) and isinstance(item.get("input"), LMap):
            out.update(_blueprint_inputs(item["input"]))
        else:
            out[str(name)] = not (isinstance(item, LMap) and "default" in item)
    return out


def _blueprint_use(ctx: Ctx, a: Automation) -> None:
    use = a.blueprint
    path = use.get("path")
    rel = f"automation/{path}" if isinstance(path, str) else None
    data = ctx.cs.blueprints.get(rel) if rel else None
    if rel is None or rel not in ctx.cs.blueprints:
        ctx.add("blueprint-missing", a.file, use.key_line("path") if "path" in use else a.line,
                f'The blueprint "{path}" isn\'t in blueprints/automation/.', a.where)
        return
    if not isinstance(data, LMap) or not isinstance(data.get("blueprint"), LMap):
        ctx.add("blueprint-missing", a.file, use.key_line("path"),
                f'The blueprint file "blueprints/{rel}" couldn\'t be read (see its own finding).', a.where)
        return
    declared = _blueprint_inputs(data["blueprint"].get("input"))
    given = use.get("input") if isinstance(use.get("input"), LMap) else LMap()
    for name, required in declared.items():
        if required and name not in given:
            ctx.add("blueprint-input-missing", a.file, use.line,
                    f'The blueprint setting "{name}" has no default and isn\'t filled in.', a.where)
    for name in given:
        if str(name) not in declared:
            ctx.add("blueprint-input-unknown", a.file, given.key_line(name),
                    f'The blueprint has no setting called "{name}".{suggest(name, declared)}', a.where)


# ------------------------------------------------------------------ old syntax

def _old_syntax(ctx: Ctx, owner: Automation | Script) -> None:
    if isinstance(owner, Automation):
        for old, new in (("trigger", "triggers"), ("condition", "conditions"), ("action", "actions")):
            if old in owner.raw and new not in owner.raw:
                ctx.add("old-plural-keys", owner.file, owner.raw.key_line(old),
                        f'Uses "{old}:" — the current name is "{new}:".', owner.where)
    for trigger, container, index, _ in all_triggers(owner):
        if isinstance(trigger, LMap) and "platform" in trigger and "trigger" not in trigger:
            ctx.add("old-platform-key", file(trigger, owner.file), trigger.key_line("platform"),
                    f'Uses "platform: {trigger.get("platform")}" — the current way is "trigger: {trigger.get("platform")}".', owner.where)
    for step in iter_steps(owner.actions):
        item = step.step
        if not isinstance(item, LMap):
            continue
        if "service" in item and "action" not in item:
            ctx.add("old-service-key", file(item, owner.file), item.key_line("service"),
                    f'Uses "service: {item.get("service")}" — the current way is "action: {item.get("service")}".', owner.where)
        for old in ("data_template", "service_template"):
            if old in item:
                ctx.add("old-data-template", file(item, owner.file), item.key_line(old),
                        f'Uses "{old}:".', owner.where)


# ------------------------------------------------------------------ triggers

def _triggers(ctx: Ctx, a: Automation) -> None:
    triggers = a.triggers
    seen: dict[str, int] = {}
    enabled = 0
    for trigger, container, index, is_wait in all_triggers(a):
        _check_trigger(ctx, a, trigger, container, index)
        if is_wait or not isinstance(trigger, LMap):
            continue
        if not is_disabled(trigger):
            enabled += 1
        sig = signature(trigger)
        if sig in seen:
            ctx.add("duplicate-trigger", file(trigger, a.file), trigger.line,
                    f"This trigger is the same as the one on line {seen[sig]}.", a.where)
        else:
            seen[sig] = trigger.line
        reason = chatty_reason(trigger)
        if reason and not a.conditions and not is_disabled(trigger):
            ctx.add("chatty-trigger", file(trigger, a.file), trigger.line,
                    f"This trigger has no filter and the automation has no conditions: {reason}.", a.where)
    if triggers and enabled == 0 and all(isinstance(t, LMap) for t in triggers):
        ctx.add("all-triggers-disabled", a.file, a.line, f"All {len(triggers)} trigger(s) have enabled: false.", a.where)


def _bool_problem(ctx: Ctx, owner: Any, container: Any, key: Any, where: str, what: str) -> bool:
    item = raw(container, key)
    if item is not None and item.tag == "tag:yaml.org,2002:bool" and item.style is None:
        word = item.text
        ctx.add("yaml-boolean-state", file(container, owner.file), line(container, key),
                f'{what} {word} has no quotes, so it is read as {"true" if word.lower() in ("on", "yes", "true", "y") else "false"} instead of the word "{word}".',
                where, fix=f'Write it as "{word.lower()}" with quotes.')
        return True
    return False


def _values_with_bool_check(ctx: Ctx, owner: Any, trigger: LMap, key: str, where: str, what: str) -> list:
    value = trigger.get(key)
    if isinstance(value, LList):
        for index in range(len(value)):
            _bool_problem(ctx, owner, value, index, where, what)
        return list(value)
    _bool_problem(ctx, owner, trigger, key, where, what)
    return as_list(value)


def _check_entity_field(ctx: Ctx, owner: Any, container: LMap, key: str, where: str, allow_template: bool = False) -> list[str]:
    value = container.get(key)
    entities = entity_ids_in(value)
    for eid in entities:
        if is_template(eid):
            if not allow_template:
                ctx.add("template-not-allowed", file(container, owner.file), container.key_line(key),
                        f'"{key}:" here can\'t be a template.', where)
        elif not is_entity_id(eid) and not REGISTRY_ID_RE.match(eid) and eid.lower() not in ("all", "none"):
            ctx.add("invalid-entity-id", file(container, owner.file), container.key_line(key),
                    f'"{eid}" isn\'t a valid entity name.' + (" Entity names are always in small letters." if eid.lower() != eid else ""), where)
    return [e for e in entities if not is_template(e)]


def _check_duration(ctx: Ctx, owner: Any, container: LMap, key: str, where: str) -> None:
    if key not in container:
        return
    value = container.get(key)
    item = raw(container, key)
    if item is not None and item.tag == "tag:yaml.org,2002:int" and ":" in item.text and item.style is None:
        if item.text.count(":") == 1:
            ctx.add("yaml-number-time", file(container, owner.file), container.key_line(key),
                    f'{key}: {item.text} has no quotes, so it is read as {value} seconds — not {item.text.split(":")[0]} hour(s) and {item.text.split(":")[1]} minutes.',
                    where, severity=WARNING, fix=f'Write it as "{item.text}:00" with quotes if you meant hours and minutes.')
        return
    if isinstance(value, (HATag,)) or value is None:
        return
    if isinstance(value, str) and is_template(value):
        return
    if isinstance(value, LMap) and any(is_template(v) for v in value.values()):
        return
    if duration_seconds(value) is None:
        shown = value if not isinstance(value, (dict, list)) else "this block"
        ctx.add("invalid-duration", file(container, owner.file), container.key_line(key),
                f'{key}: {shown} isn\'t a length of time Home Assistant understands.', where)


def _check_clock(ctx: Ctx, owner: Any, container: Any, key: Any, value: Any, where: str, label: str) -> int | None:
    item = raw(container, key)
    if item is not None and item.tag == "tag:yaml.org,2002:int" and ":" in item.text and item.style is None:
        ctx.add("yaml-number-time", file(container, owner.file), line(container, key),
                f'{label} {item.text} has no quotes, so it is read as the number {value}.', where,
                fix=f'Write it as "{item.text}" with quotes (or "{item.text}:00").')
        return None
    if isinstance(value, str):
        if is_template(value):
            ctx.add("template-not-allowed", file(container, owner.file), line(container, key), f"{label} can't be a template.", where)
            return None
        if is_entity_id(value):
            return None  # a time taken from an input_datetime or sensor
        seconds = parse_clock(value)
        if seconds is None:
            ctx.add("invalid-time", file(container, owner.file), line(container, key), f'{label} "{value}" isn\'t a valid time of day.', where)
        return seconds
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        ctx.add("invalid-time", file(container, owner.file), line(container, key), f"{label} {value} is a number, not a time of day.", where)
    return None


def _check_trigger(ctx: Ctx, owner: Any, trigger: Any, container: Any, index: int) -> None:
    where = owner.where
    if isinstance(trigger, HATag) or trigger is None:
        return
    if not isinstance(trigger, LMap):
        ctx.add("unknown-trigger-type", file(container, owner.file), line(container, index), "This trigger isn't a block of settings.", where)
        return
    ttype = trigger_type(trigger)
    tfile = file(trigger, owner.file)
    if ttype is None:
        ctx.add("unknown-trigger-type", tfile, trigger.line, "This trigger doesn't say what kind it is (trigger: state, time …).", where)
        return
    if ttype not in TRIGGER_TYPES and "." not in ttype:
        key = "trigger" if "trigger" in trigger else "platform"
        ctx.add("unknown-trigger-type", tfile, trigger.key_line(key), f'"{ttype}" isn\'t a kind of trigger.{suggest(ttype, TRIGGER_TYPES)}', where)
        return
    if ttype == "state":
        entities = _check_entity_field(ctx, owner, trigger, "entity_id", where)
        if "entity_id" not in trigger:
            ctx.add("invalid-entity-id", tfile, trigger.line, "This state trigger has no entity_id:.", where)
        has_attribute = "attribute" in trigger
        values: dict[str, list] = {}
        for key in ("to", "from", "not_to", "not_from"):
            if key not in trigger:
                continue
            if not has_attribute:
                values[key] = _values_with_bool_check(ctx, owner, trigger, key, where, f"{key}:")
            else:
                values[key] = as_list(trigger.get(key))
            for value in values[key]:
                if is_template(value):
                    ctx.add("template-not-allowed", tfile, trigger.key_line(key), f'"{key}:" in a state trigger can\'t be a template.', where)
        to, frm = values.get("to"), values.get("from")
        if not has_attribute and to and frm and len(to) == 1 and len(frm) == 1 and to[0] == frm[0] and isinstance(to[0], str):
            ctx.add("same-from-to", tfile, trigger.key_line("to"), f'from: and to: are both "{to[0]}".', where)
        lowered = {str(v).lower() for v in (to or []) + (frm or [])}
        if lowered & UNAVAILABLE and "for" not in trigger:
            ctx.add("trigger-on-unavailable", tfile, trigger.key_line("to" if "to" in trigger else "from"),
                    f'It reacts to {quote_list(sorted(lowered & UNAVAILABLE))}.', where)
        elif (to and not frm and "not_from" not in trigger and not has_attribute
              and not lowered & UNAVAILABLE and all(isinstance(v, str) for v in to)
              and not all(e.split(".", 1)[0] in NEVER_UNAVAILABLE_DOMAINS for e in entities)):
            ctx.add("reconnect-false-trigger", tfile, trigger.key_line("to"),
                    f'It fires on any change to {quote_list(to)} — including from "unavailable".', where)
        _check_duration(ctx, owner, trigger, "for", where)
    elif ttype == "numeric_state":
        entities = _check_entity_field(ctx, owner, trigger, "entity_id", where)
        if "attribute" not in trigger and "value_template" not in trigger:
            for eid in entities:
                if eid.split(".", 1)[0] in NON_NUMERIC_DOMAINS:
                    ctx.add("numeric-on-non-numeric", tfile, trigger.key_line("entity_id"),
                            f"{eid} has states like on/off, not numbers.", where)
        _check_range(ctx, owner, trigger, where)
        _check_duration(ctx, owner, trigger, "for", where)
    elif ttype == "time":
        at = trigger.get("at")
        if isinstance(at, LList):
            for i, value in enumerate(at):
                _check_clock(ctx, owner, at, i, value, where, "at:")
        elif not isinstance(at, LMap):
            _check_clock(ctx, owner, trigger, "at", at, where, "at:")
    elif ttype == "time_pattern":
        for key, top in (("hours", 23), ("minutes", 59), ("seconds", 59)):
            if key in trigger and not _pattern_ok(trigger.get(key), top):
                ctx.add("invalid-time-pattern", tfile, trigger.key_line(key),
                        f'{key}: {trigger.get(key)} is out of range (0–{top}) or not written like "/5".', where)
    elif ttype == "sun":
        event = trigger.get("event")
        if is_template(event):
            ctx.add("template-not-allowed", tfile, trigger.key_line("event"), "event: in a sun trigger can't be a template.", where)
        elif event not in ("sunrise", "sunset"):
            ctx.add("unknown-trigger-type", tfile, trigger.key_line("event") if "event" in trigger else trigger.line,
                    f'A sun trigger needs event: sunrise or event: sunset (found "{event}").', where)
        _check_duration(ctx, owner, trigger, "offset", where)
    elif ttype == "template":
        template = trigger.get("value_template")
        if not is_template(template):
            ctx.add("template-trigger-static", tfile, trigger.key_line("value_template") if "value_template" in trigger else trigger.line,
                    "The value_template has no {{ }} code in it." if template is not None else "The template trigger has no value_template:.", where)
        _check_duration(ctx, owner, trigger, "for", where)
    elif ttype == "zone":
        _check_entity_field(ctx, owner, trigger, "entity_id", where)


def _pattern_ok(value: Any, top: int) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return 0 <= value <= top
    text = str(value).strip()
    if text == "*":
        return True
    if text.startswith("/"):
        text = text[1:]
        return text.isdigit() and 0 < int(text) <= top
    return text.isdigit() and 0 <= int(text) <= top


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _check_range(ctx: Ctx, owner: Any, item: LMap, where: str) -> None:
    for key in ("above", "below"):
        if is_template(item.get(key)):
            ctx.add("template-not-allowed", file(item, owner.file), item.key_line(key),
                    f'{key}: can\'t be a template. Use an input_number entity, or a template trigger/condition.', where)
    above, below = _number(item.get("above")), _number(item.get("below"))
    if above is not None and below is not None and above >= below:
        ctx.add("impossible-range", file(item, owner.file), item.key_line("above"),
                f"It needs to be above {item.get('above')} and below {item.get('below')} at the same time.", where)


# ------------------------------------------------------------------ conditions

def _trigger_ids(a: Automation) -> set[str]:
    ids = set()
    for index, trigger in enumerate(a.triggers):
        if isinstance(trigger, LMap):
            ids.add(str(trigger.get("id")) if trigger.get("id") is not None else str(index))
    return ids


def _conditions(ctx: Ctx, owner: Automation | Script) -> None:
    where = owner.where
    ids = _trigger_ids(owner) if isinstance(owner, Automation) else None
    for cond, container, index in all_conditions(owner):
        if isinstance(cond, HATag) or cond is None:
            continue
        if isinstance(cond, str):
            if not is_template(cond):
                ctx.add("unknown-condition-type", file(container, owner.file), line(container, index),
                        f'"{cond}" isn\'t a condition.', where)
            continue
        if not isinstance(cond, LMap):
            continue
        ctype = condition_type(cond)
        cfile = file(cond, owner.file)
        if ctype is None:
            if "condition" not in cond:
                continue  # an action step mistaken for a condition is reported elsewhere
            ctx.add("unknown-condition-type", cfile, cond.line, "This condition doesn't say what kind it is.", where)
            continue
        if ctype not in CONDITION_TYPES and "." not in ctype:
            ctx.add("unknown-condition-type", cfile, cond.key_line("condition"),
                    f'"{ctype}" isn\'t a kind of condition.{suggest(ctype, CONDITION_TYPES)}', where)
            continue
        if ctype == "state":
            _check_entity_field(ctx, owner, cond, "entity_id", where)
            if "attribute" not in cond:
                values = _values_with_bool_check(ctx, owner, cond, "state", where, "state:")
            else:
                values = as_list(cond.get("state"))
            if any(is_template(v) for v in values):
                ctx.add("template-not-allowed", cfile, cond.key_line("state"), "state: in a state condition can't be a template.", where)
            _check_duration(ctx, owner, cond, "for", where)
        elif ctype == "numeric_state":
            entities = _check_entity_field(ctx, owner, cond, "entity_id", where)
            if "attribute" not in cond and "value_template" not in cond:
                for eid in entities:
                    if eid.split(".", 1)[0] in NON_NUMERIC_DOMAINS:
                        ctx.add("numeric-on-non-numeric", cfile, cond.key_line("entity_id"), f"{eid} has states like on/off, not numbers.", where)
            _check_range(ctx, owner, cond, where)
        elif ctype == "time":
            for key in ("after", "before"):
                if key in cond:
                    _check_clock(ctx, owner, cond, key, cond.get(key), where, f"{key}:")
            for day in as_list(cond.get("weekday")):
                if not isinstance(day, str) or day.lower() not in WEEKDAYS:
                    ctx.add("invalid-time", cfile, cond.key_line("weekday"),
                            f'weekday: "{day}" isn\'t a day. Use mon, tue, wed, thu, fri, sat or sun.', where)
        elif ctype == "sun":
            if cond.get("after") == "sunset" and cond.get("before") == "sunrise":
                ctx.add("sun-condition-never", cfile, cond.line, "This sun condition asks for after sunset AND before sunrise.", where)
        elif ctype == "trigger" and ids is not None:
            for wanted in as_list(cond.get("id")):
                if str(wanted) not in ids and not is_template(wanted):
                    ctx.add("unknown-trigger-id", cfile, cond.key_line("id"),
                            f'No trigger has id "{wanted}".{suggest(wanted, ids)}', where)
    if isinstance(owner, Automation):
        _contradictions(ctx, owner)


def _and_conditions(conditions: list) -> list[LMap]:
    out: list[LMap] = []
    for cond in conditions:
        if isinstance(cond, LMap) and not is_disabled(cond):
            ctype = condition_type(cond)
            if ctype == "and":
                out.extend(_and_conditions(as_list(cond.get("conditions", cond.get("and")))))
            elif ctype in ("state", "numeric_state"):
                out.append(cond)
    return out


def _contradictions(ctx: Ctx, a: Automation) -> None:
    states: dict[str, tuple[set, LMap]] = {}
    ranges: dict[str, list] = {}
    for cond in _and_conditions(a.conditions):
        entities = entity_ids_in(cond.get("entity_id"))
        if len(entities) != 1 or "attribute" in cond or "value_template" in cond or cond.get("match") == "any":
            continue
        eid = entities[0]
        if condition_type(cond) == "state":
            wanted = {str(v) for v in as_list(cond.get("state")) if isinstance(v, (str, int, float)) and not is_template(v)}
            if not wanted:
                continue
            if eid in states and not (states[eid][0] & wanted):
                ctx.add("contradictory-conditions", file(cond, a.file), cond.line,
                        f"{eid} must be {quote_list(sorted(states[eid][0]))} (line {states[eid][1].line}) and also {quote_list(sorted(wanted))} here.", a.where)
            states[eid] = (wanted, cond)
        else:
            above, below = _number(cond.get("above")), _number(cond.get("below"))
            bounds = ranges.setdefault(eid, [None, None, cond])
            if above is not None:
                bounds[0] = above if bounds[0] is None else max(bounds[0], above)
            if below is not None:
                bounds[1] = below if bounds[1] is None else min(bounds[1], below)
            if bounds[0] is not None and bounds[1] is not None and bounds[0] >= bounds[1] and bounds[2] is not cond:
                ctx.add("contradictory-conditions", file(cond, a.file), cond.line,
                        f"{eid} would have to be above {bounds[0]:g} and below {bounds[1]:g} at once.", a.where)


# ------------------------------------------------------------------ mode, waits and storms

def _waits(owner: Automation | Script) -> list:
    return [s for s in iter_steps(owner.actions) if s.kind in WAIT_KINDS and not is_disabled(s.step)]


def _mode_and_waits(ctx: Ctx, a: Automation) -> None:
    waits = _waits(a)
    mode = a.mode
    chatty = [chatty_reason(t) for t in a.triggers if isinstance(t, LMap) and not is_disabled(t)]
    chatty = [c for c in chatty if c]
    if mode == "single" and waits and "max_exceeded" not in a.raw:
        first = waits[0]
        length = duration_seconds(first.step.get(first.kind)) if first.kind == "delay" else None
        how = f"waits {human_duration(length)}" if length else ("waits" if first.kind != "delay" else "has a delay")
        ctx.add("single-mode-wait", file(first.step, a.file), first.step.line,
                f"{a.where} {how} while in mode: single (the default), so triggers that happen during the wait are dropped.", a.where)
    if mode in ("queued", "parallel"):
        maximum = a.raw.get("max")
        total_delay = sum(duration_seconds(s.step.get("delay")) or 0 for s in waits if s.kind == "delay")
        reasons = []
        if isinstance(maximum, int) and not isinstance(maximum, bool) and maximum > 25:
            reasons.append(f"max: {maximum} allows up to {maximum} runs at once")
        if chatty:
            reasons.append(f"its trigger is very busy ({chatty[0]})")
        if mode == "queued" and total_delay >= 600:
            reasons.append(f"each run waits {human_duration(total_delay)}, so a queue can build up")
        if reasons:
            ctx.add("queue-storm", a.file, a.key_line("mode"), f"mode: {mode} — " + "; ".join(reasons) + ".", a.where)
    if mode == "restart" and chatty and waits:
        ctx.add("restart-storm", a.file, a.key_line("mode"),
                f"mode: restart with a very busy trigger ({chatty[0]}), so the steps after the wait may never be reached.", a.where)
    _self_trigger(ctx, a)


def _self_trigger(ctx: Ctx, a: Automation) -> None:
    from .common import all_effects

    effects = all_effects(a.actions)
    for trigger in a.triggers:
        if trigger_type(trigger) != "state" or is_disabled(trigger):
            continue
        if any(key in trigger for key in ("to", "from", "not_to", "not_from")):
            continue  # setting it to the state that triggered it changes nothing, so no loop
        for eid in entity_ids_in(trigger.get("entity_id")):
            if not effects.get(eid):
                continue
            ctx.add("self-trigger-loop", file(trigger, a.file), trigger.line,
                    f"It is triggered by any change of {eid}, and it changes {eid} itself.", a.where,
                    severity=ERROR if a.mode in ("queued", "parallel") else WARNING)


# ------------------------------------------------------------------ can never fire

def _never_fires(ctx: Ctx, a: Automation) -> None:
    times = []
    for trigger in a.triggers:
        if trigger_type(trigger) != "time" or is_disabled(trigger):
            return
        for value in as_list(trigger.get("at")):
            seconds = parse_clock(value) if isinstance(value, str) else None
            if seconds is None:
                return
            times.append((seconds, trigger))
    if not times:
        return
    for cond in a.conditions:
        if condition_type(cond) != "time" or not isinstance(cond, LMap) or "weekday" in cond:
            continue
        after = parse_clock(cond.get("after")) if isinstance(cond.get("after"), str) else None
        before = parse_clock(cond.get("before")) if isinstance(cond.get("before"), str) else None
        if after is None and before is None:
            continue

        def inside(t: int) -> bool:
            if after is not None and before is not None:
                return after <= t < before if after < before else (t >= after or t < before)
            if after is not None:
                return t >= after
            return t < before  # type: ignore[operator]

        if not any(inside(t) for t, _ in times):
            shown = ", ".join(sorted({f"{t // 3600:02d}:{t % 3600 // 60:02d}" for t, _ in times}))
            ctx.add("trigger-outside-condition", file(cond, a.file), cond.line,
                    f"It is triggered at {shown}, but the time condition only allows "
                    + (f"after {cond.get('after')} " if after is not None else "")
                    + (f"before {cond.get('before')}" if before is not None else "") + ".", a.where)


# ------------------------------------------------------------------ steps

def _steps(ctx: Ctx, owner: Automation | Script) -> None:
    where = owner.where
    for step in iter_steps(owner.actions):
        item = step.step
        if isinstance(item, (HATag, str)) or item is None:
            if step.kind == "unknown":
                ctx.add("unknown-action-type", file(step.container, owner.file), line(step.container, step.index),
                        f'"{item}" isn\'t a step Home Assistant understands.', where)
            continue
        if not isinstance(item, LMap):
            continue
        sfile = file(item, owner.file)
        if step.kind == "unknown":
            first = next(iter(item), "")
            ctx.add("unknown-action-type", sfile, item.line,
                    f'A step starting with "{first}:" isn\'t one Home Assistant understands.{suggest(first, ["action", "delay", "choose", "if", "repeat", "wait_template", "wait_for_trigger", "condition", "variables", "event", "scene", "parallel", "sequence", "stop"])}',
                    where)
        elif step.kind == "delay":
            _check_duration(ctx, owner, item, "delay", where)
        elif step.kind in ("wait_template", "wait_for_trigger"):
            if "timeout" not in item:
                ctx.add("wait-without-timeout", sfile, item.key_line(step.kind),
                        f"This {step.kind} has no timeout:, so it can wait forever.", where)
            _check_duration(ctx, owner, item, "timeout", where)
        elif step.kind == "repeat" and isinstance(item.get("repeat"), LMap):
            repeat = item["repeat"]
            if ("while" in repeat or "until" in repeat) and not any(s.kind in WAIT_KINDS for s in iter_steps(repeat.get("sequence"))):
                ctx.add("repeat-no-pause", sfile, item.line,
                        f"This repeat ({'while' if 'while' in repeat else 'until'}) has no delay or wait inside.", where)
        elif step.kind == "scene":
            pass
    for steps in iter_step_lists(owner.actions):
        _on_off_same_moment(ctx, owner, steps)


def _on_off_same_moment(ctx: Ctx, owner: Any, steps: list) -> None:
    last: dict[str, tuple[str, int]] = {}
    for step in steps:
        kind = None
        if isinstance(step, LMap):
            from .common import step_kind

            kind = step_kind(step)
        if kind in WAIT_KINDS or kind in ("choose", "if", "repeat", "parallel", "sequence", "condition"):
            last.clear()
            continue
        if kind != "call_service" or is_disabled(step):
            continue
        for eid, effect in step_effects(step):
            if effect in ("toggle", "changed"):
                last.pop(eid, None)
                continue
            if eid in last and opposite(last[eid][0], effect):
                ctx.add("on-off-same-moment", file(step, owner.file), step.line,
                        f"{eid} is set to {last[eid][0]} on line {last[eid][1]} and straight to {effect} here.", owner.where)
            last[eid] = (effect, step.line)


# ------------------------------------------------------------------ size and similarity

def _size(ctx: Ctx, owner: Automation | Script) -> None:
    steps = list(iter_steps(owner.actions))
    count = len(steps)
    depth = max((s.depth for s in steps), default=0)
    if count > 75:
        ctx.add("long-automation", owner.file, owner.line, f"{owner.where} has {count} steps.", owner.where, severity=WARNING)
    elif count > 30:
        ctx.add("long-automation", owner.file, owner.line, f"{owner.where} has {count} steps.", owner.where)
    if depth >= 6:
        ctx.add("deep-nesting", owner.file, owner.line, f"Steps are nested {depth} levels deep.", owner.where, severity=WARNING)
    elif depth >= 4:
        ctx.add("deep-nesting", owner.file, owner.line, f"Steps are nested {depth} levels deep.", owner.where)


def _shape(value: Any, key: Any = None) -> Any:
    from ..util import looks_like_known_entity

    if isinstance(value, dict):
        return {k: _shape(v, k) for k, v in value.items() if k not in ("id", "alias", "description")}
    if isinstance(value, list):
        return [_shape(v, key) for v in value]
    if isinstance(value, str) and key not in ("action", "service", "trigger", "platform", "condition"):
        if looks_like_known_entity(value) or "," in value and all(looks_like_known_entity(p.strip()) for p in value.split(",")):
            return "<entity>"
        if parse_clock(value) is not None:
            return "<time>"
    return value


def _similar_automations(ctx: Ctx) -> None:
    import json

    from ..yamlio import to_plain

    groups: dict[str, list[Automation]] = defaultdict(list)
    for a in ctx.model.automations:
        if a.blueprint is not None or not a.triggers or not a.actions:
            continue
        shape = _shape(to_plain({k: v for k, v in a.raw.items()}))
        text = json.dumps(shape, sort_keys=True, default=str)
        if "<entity>" in text:
            groups[text].append(a)
    for items in groups.values():
        if len(items) >= 3:
            first = items[0]
            others = [f"{x.where} ({x.file}, line {x.line})" for x in items[1:]]
            ctx.add("similar-automations", first.file, first.line,
                    f"{first.where} and {len(others)} other(s) differ only in the entities they use: " + "; ".join(others) + ".", first.where)


def _repeated_steps(ctx: Ctx) -> None:
    window = 3
    seen: dict[str, list[tuple[Any, int]]] = defaultdict(list)
    for where, actions, owner in ctx.model.iter_action_lists():
        if isinstance(owner, Automation) and owner.blueprint is not None:
            continue
        steps = [s for s in actions if isinstance(s, LMap)]
        if len(steps) < window:
            continue
        done_here: set[str] = set()
        for start in range(len(steps) - window + 1):
            chunk = steps[start:start + window]
            key = "|".join(signature(s, drop=("alias", "id", "enabled")) for s in chunk)
            if key in done_here:
                continue
            done_here.add(key)
            seen[key].append((owner, chunk[0].line))
    reported: set[frozenset] = set()
    for key, places in seen.items():
        owners = {id(o) for o, _ in places}
        if len(owners) < 2:
            continue
        group = frozenset(owners)
        if group in reported:
            continue
        reported.add(group)
        owner, first_line = places[0]
        others = [f"{o.where} ({o.file}, line {ln})" for o, ln in places[1:]]
        ctx.add("repeated-steps", owner.file, first_line,
                f"The same {window} or more steps also appear in: " + "; ".join(others) + ".", owner.where)
