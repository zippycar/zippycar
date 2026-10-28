"""Shared helpers for the checks: walking through steps, triggers and conditions."""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass
from typing import Any, Iterator

from ..catalog import Findings
from ..configtree import ConfigSet
from ..model import Automation, Model, Script
from ..registry import Registry
from ..rules import HAVersion, RuleBook
from ..util import as_list, entity_ids_in, is_template
from ..yamlio import HATag, LList, LMap, Raw, to_plain

TRIGGER_TYPES = {
    "state", "numeric_state", "event", "homeassistant", "mqtt", "sun", "tag", "template", "time",
    "time_pattern", "webhook", "zone", "geo_location", "device", "calendar", "conversation",
    "persistent_notification",
}
STATE_LIKE_TRIGGERS = {"state", "numeric_state", "template", "zone", "geo_location", "device"}
CONDITION_TYPES = {"and", "or", "not", "state", "numeric_state", "template", "time", "sun", "zone", "trigger", "device"}
AUTOMATION_KEYS = {
    "id", "alias", "description", "triggers", "trigger", "conditions", "condition", "actions", "action",
    "mode", "max", "max_exceeded", "variables", "trigger_variables", "initial_state", "trace", "use_blueprint",
}
SCRIPT_MODES = {"single", "restart", "queued", "parallel"}
MAX_EXCEEDED = {"silent", "critical", "fatal", "error", "warning", "warn", "info", "debug", "notset"}
WAIT_KINDS = {"delay", "wait_template", "wait_for_trigger"}

CHATTY_ENTITIES = {"sun.sun", "sensor.time", "sensor.date_time", "sensor.date_time_iso", "sensor.time_utc", "sensor.internet_time", "sensor.date_time_utc"}
CHATTY_DOMAINS = {"sensor", "weather", "media_player", "sun", "device_tracker", "person", "climate", "water_heater", "camera"}
CHATTY_WORDS = (
    "power", "energy", "current", "voltage", "watt", "temperature", "humidity", "pressure", "illuminance",
    "lux", "rssi", "signal", "linkquality", "lqi", "uptime", "cpu", "memory", "load", "speed", "download",
    "upload", "throughput", "consumption", "co2", "pm2", "pm10", "voc", "noise", "distance", "wind", "rain",
)
CHATTY_ATTRIBUTES = {"elevation", "azimuth", "media_position", "media_position_updated_at", "current_temperature", "rssi", "latitude", "longitude", "gps_accuracy", "speed"}


@dataclass
class Ctx:
    cs: ConfigSet
    model: Model
    reg: Registry
    findings: Findings
    rules: RuleBook
    version: HAVersion

    def add(self, code: str, file: str, line: int, detail: str, where: str = "", fix: str = "", severity: str | None = None,
            **extra: str) -> None:
        self.findings.add(code, file, line, detail, where, fix, severity, **extra)


# ------------------------------------------------------------------ small helpers

def raw(container: Any, key: Any) -> Raw | None:
    if isinstance(container, LMap):
        return container.raw_of(key)
    if isinstance(container, LList) and isinstance(key, int) and key < len(container.raw_items):
        return container.raw_items[key]
    return None


def line(container: Any, key: Any = None) -> int:
    if isinstance(container, LMap):
        return container.key_line(key) if key is not None else container.line
    if isinstance(container, LList):
        return container.item_line(key) if isinstance(key, int) else container.line
    return getattr(container, "line", 0)


def file(container: Any, default: str = "") -> str:
    return getattr(container, "file", "") or default


def suggest(word: str, choices: Any) -> str:
    match = difflib.get_close_matches(str(word), [str(c) for c in choices], n=1, cutoff=0.6)
    return f' Did you mean "{match[0]}"?' if match else ""


def is_disabled(item: Any) -> bool:
    return isinstance(item, LMap) and item.get("enabled") is False


def signature(value: Any, drop: tuple[str, ...] = ("id", "alias", "enabled", "variables")) -> str:
    plain = to_plain(value)
    if isinstance(plain, dict):
        plain = {k: v for k, v in plain.items() if k not in drop}
    return json.dumps(plain, sort_keys=True, default=str)


def trigger_type(trigger: Any) -> str | None:
    if not isinstance(trigger, LMap):
        return None
    value = trigger.get("trigger", trigger.get("platform"))
    return value if isinstance(value, str) else None


def condition_type(condition: Any) -> str | None:
    if isinstance(condition, str):
        return "template" if is_template(condition) else None
    if not isinstance(condition, LMap):
        return None
    value = condition.get("condition")
    if isinstance(value, str):
        return "template" if is_template(value) else value
    for short in ("and", "or", "not"):
        if short in condition:
            return short
    return None


def step_kind(step: Any) -> str:
    if isinstance(step, str):
        return "template_condition" if is_template(step) else "unknown"
    if isinstance(step, HATag):
        return "input"
    if not isinstance(step, LMap):
        return "unknown"
    for key, kind in (
        ("delay", "delay"), ("wait_template", "wait_template"), ("wait_for_trigger", "wait_for_trigger"),
        ("repeat", "repeat"), ("choose", "choose"), ("if", "if"), ("parallel", "parallel"),
        ("sequence", "sequence"), ("variables", "variables"), ("stop", "stop"),
        ("set_conversation_response", "set_conversation_response"), ("event", "event"), ("scene", "scene"),
        ("condition", "condition"), ("action", "call_service"), ("service", "call_service"),
        ("service_template", "call_service"),
    ):
        if key in step:
            return kind
    if "device_id" in step and "domain" in step:
        return "device"
    if any(k in step for k in ("and", "or", "not")):
        return "condition"
    return "unknown"


# ------------------------------------------------------------------ walking steps

@dataclass
class Step:
    step: Any
    container: Any
    index: int
    depth: int
    conditional: bool
    kind: str


def iter_steps(actions: Any, depth: int = 0, conditional: bool = False) -> Iterator[Step]:
    """Every step, including steps inside choose / if / repeat / parallel / sequence."""

    items = actions if isinstance(actions, list) else as_list(actions)
    gated = conditional
    for index, item in enumerate(items):
        kind = step_kind(item)
        yield Step(item, actions, index, depth, gated, kind)
        if kind in ("condition", "template_condition"):
            gated = True  # everything after a condition step only runs if it passes
        if not isinstance(item, LMap):
            continue
        if kind == "choose":
            for option in as_list(item.get("choose")):
                if isinstance(option, LMap):
                    yield from iter_steps(option.get("sequence"), depth + 1, True)
            if "default" in item:
                yield from iter_steps(item.get("default"), depth + 1, True)
        elif kind == "if":
            yield from iter_steps(item.get("then"), depth + 1, True)
            if "else" in item:
                yield from iter_steps(item.get("else"), depth + 1, True)
        elif kind == "repeat" and isinstance(item.get("repeat"), LMap):
            yield from iter_steps(item["repeat"].get("sequence"), depth + 1, True)
        elif kind == "parallel":
            for branch in as_list(item.get("parallel")):
                if isinstance(branch, LMap) and "sequence" in branch and step_kind(branch) == "sequence":
                    yield from iter_steps(branch.get("sequence"), depth + 1, gated)
                else:
                    yield from iter_steps([branch] if not isinstance(branch, list) else branch, depth + 1, gated)
        elif kind == "sequence":
            yield from iter_steps(item.get("sequence"), depth + 1, gated)


def iter_step_lists(actions: Any) -> Iterator[list]:
    """Every list of steps (the top level and each nested sequence)."""

    if isinstance(actions, list):
        yield actions
    for step in iter_steps(actions):
        item = step.step
        if not isinstance(item, LMap):
            continue
        nested: list = []
        if step.kind == "choose":
            nested = [o.get("sequence") for o in as_list(item.get("choose")) if isinstance(o, LMap)] + [item.get("default")]
        elif step.kind == "if":
            nested = [item.get("then"), item.get("else")]
        elif step.kind == "repeat" and isinstance(item.get("repeat"), LMap):
            nested = [item["repeat"].get("sequence")]
        elif step.kind == "sequence":
            nested = [item.get("sequence")]
        for value in nested:
            if isinstance(value, list):
                yield value


def iter_conditions(conditions: Any, depth: int = 0) -> Iterator[tuple[Any, Any, int]]:
    """(condition, the list it is in, index) for every condition, including nested and/or/not."""

    items = conditions if isinstance(conditions, list) else as_list(conditions)
    for index, item in enumerate(items):
        yield item, conditions, index
        if isinstance(item, LMap):
            ctype = condition_type(item)
            if ctype in ("and", "or", "not"):
                inner = item.get("conditions") if "conditions" in item else item.get(ctype)
                yield from iter_conditions(inner, depth + 1)


def all_conditions(owner: Automation | Script) -> Iterator[tuple[Any, Any, int]]:
    """Every condition in an automation or script: top level, condition steps, choose, if, repeat."""

    if isinstance(owner, Automation):
        yield from iter_conditions(owner.conditions)
    for step in iter_steps(owner.actions):
        item = step.step
        if not isinstance(item, LMap):
            continue
        if step.kind == "condition":
            yield item, step.container, step.index
            ctype = condition_type(item)
            if ctype in ("and", "or", "not"):
                inner = item.get("conditions") if "conditions" in item else item.get(ctype)
                yield from iter_conditions(inner)
        elif step.kind == "choose":
            for option in as_list(item.get("choose")):
                if isinstance(option, LMap):
                    yield from iter_conditions(option.get("conditions"))
        elif step.kind == "if":
            yield from iter_conditions(item.get("if"))
        elif step.kind == "repeat" and isinstance(item.get("repeat"), LMap):
            for key in ("while", "until"):
                if key in item["repeat"]:
                    yield from iter_conditions(item["repeat"][key])


def all_triggers(owner: Automation | Script) -> Iterator[tuple[Any, Any, int, bool]]:
    """(trigger, container, index, is_wait) for automation triggers and wait_for_trigger triggers."""

    if isinstance(owner, Automation):
        triggers = owner.triggers
        for index, trigger in enumerate(triggers):
            yield trigger, triggers, index, False
    for step in iter_steps(owner.actions):
        if step.kind == "wait_for_trigger" and isinstance(step.step, LMap):
            from ..model import flatten_triggers

            waits = flatten_triggers(step.step.get("wait_for_trigger"))
            for index, trigger in enumerate(waits):
                yield trigger, waits, index, True


# ------------------------------------------------------------------ what actions do

ON_OFF = {
    "turn_on": "on", "turn_off": "off", "toggle": "toggle",
    "open_cover": "open", "close_cover": "closed", "lock": "locked", "unlock": "unlocked",
    "media_play": "playing", "media_pause": "paused", "media_stop": "paused",
    "open_valve": "open", "close_valve": "closed",
}
OPPOSITE = {"on": "off", "off": "on", "open": "closed", "closed": "open", "locked": "unlocked", "unlocked": "locked", "playing": "paused", "paused": "playing"}


def opposite(a: str, b: str) -> bool:
    return a != b and ("toggle" in (a, b) or OPPOSITE.get(a) == b)


def step_targets(step: LMap) -> list[str]:
    targets: list[str] = []
    for source in (step, step.get("target"), step.get("data")):
        if isinstance(source, LMap) and "entity_id" in source:
            for eid in entity_ids_in(source.get("entity_id")):
                if not is_template(eid):
                    targets.append(eid)
    return targets


def step_effects(step: LMap) -> list[tuple[str, str]]:
    """[(entity, effect)] for a step such as light.turn_on, e.g. ("light.hall", "on")."""

    service = step.get("action", step.get("service"))
    if not isinstance(service, str) or "." not in service or is_template(service):
        return []
    domain, name = service.split(".", 1)
    if domain in ("scene", "script", "automation", "notify", "persistent_notification"):
        return []
    effect = ON_OFF.get(name)
    if name.startswith("set_") or name in ("select_option", "increment", "decrement", "press", "reload"):
        effect = "changed"
    if effect is None:
        return []
    return [(eid, effect) for eid in step_targets(step)]


def unconditional_effects(actions: Any) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for step in iter_steps(actions):
        if step.conditional or step.kind != "call_service" or is_disabled(step.step):
            continue
        for eid, effect in step_effects(step.step):
            out.setdefault(eid, set()).add(effect)
    return out


def all_effects(actions: Any) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for step in iter_steps(actions):
        if step.kind == "call_service" and isinstance(step.step, LMap) and not is_disabled(step.step):
            for eid, effect in step_effects(step.step):
                out.setdefault(eid, set()).add(effect)
    return out


# ------------------------------------------------------------------ chatty triggers

def _chatty_name(entity_id: str) -> bool:
    if entity_id in CHATTY_ENTITIES:
        return True
    object_id = entity_id.split(".", 1)[-1]
    return any(word in object_id for word in CHATTY_WORDS)


def chatty_reason(trigger: Any) -> str | None:
    ttype = trigger_type(trigger)
    if ttype == "state":
        entities = entity_ids_in(trigger.get("entity_id"))
        filters = [k for k in ("to", "from", "not_to", "not_from") if k in trigger]
        attribute = trigger.get("attribute")
        for eid in entities:
            domain = eid.split(".", 1)[0]
            if attribute is not None:
                if str(attribute) in CHATTY_ATTRIBUTES and not filters:
                    return f'it fires every time the "{attribute}" detail of {eid} changes'
                continue
            if not filters and (domain in CHATTY_DOMAINS or _chatty_name(eid)):
                return f"it fires on every change of {eid}, including every small update of its details"
            if filters == ["to"] and trigger.get("to") is None and domain == "sensor" and _chatty_name(eid):
                return f"it fires on every new reading of {eid}"
    elif ttype == "time_pattern":
        seconds, minutes = trigger.get("seconds"), trigger.get("minutes")
        if _every(seconds, 30):
            return "it fires every few seconds"
        if seconds is None and _every(minutes, 2) and trigger.get("hours") is None:
            return "it fires every minute or two"
    elif ttype == "event":
        if trigger.get("event_type") in ("state_changed", "call_service", "*") and not trigger.get("event_data"):
            return f'it fires on every "{trigger.get("event_type")}" event in the whole system'
    elif ttype == "mqtt":
        topic = trigger.get("topic")
        if isinstance(topic, str) and ("#" in topic or "+" in topic):
            return "it listens to a whole group of MQTT topics at once"
    return None


def _every(value: Any, below: int) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    if text == "*":
        return True
    if text.startswith("/"):
        try:
            return int(text[1:]) < below
        except ValueError:
            return False
    return False
