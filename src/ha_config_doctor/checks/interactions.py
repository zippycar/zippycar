"""Checks that compare automations with each other: fights, clashes and loops."""

from __future__ import annotations

from typing import Any

from ..catalog import ERROR, WARNING
from ..model import Automation
from ..sun import yearly_ranges
from ..util import clock_text, duration_seconds, parse_clock
from ..yamlio import LMap
from .common import Ctx, condition_type, is_disabled, opposite, trigger_type, unconditional_effects


def run(ctx: Ctx) -> None:
    autos = [a for a in ctx.model.automations if a.blueprint is None]
    effects = {id(a): unconditional_effects(a.actions) for a in autos}
    _contradictory(ctx, autos, effects)
    _time_clash(ctx, autos, effects)
    _sun_overlap(ctx, autos, effects)


def _trigger_signatures(a: Automation) -> dict[str, Any]:
    import json

    from ..yamlio import to_plain

    out: dict[str, Any] = {}
    for trigger in a.triggers:
        if isinstance(trigger, LMap) and not is_disabled(trigger):
            plain = {k: v for k, v in to_plain(trigger).items() if k not in ("id", "alias", "enabled", "variables")}
            if "platform" in plain and "trigger" not in plain:
                plain["trigger"] = plain.pop("platform")
            out[json.dumps(plain, sort_keys=True, default=str)] = trigger
    return out


def _clashes(first: dict[str, set[str]], second: dict[str, set[str]]) -> list[tuple[str, str, str]]:
    found = []
    for eid in sorted(set(first) & set(second)):
        for a in sorted(first[eid]):
            for b in sorted(second[eid]):
                if a != "changed" and b != "changed" and opposite(a, b):
                    found.append((eid, a, b))
    return found


def _contradictory(ctx: Ctx, autos: list[Automation], effects: dict[int, dict]) -> None:
    sigs = {id(a): _trigger_signatures(a) for a in autos}
    for i, first in enumerate(autos):
        for second in autos[i + 1:]:
            shared = set(sigs[id(first)]) & set(sigs[id(second)])
            if not shared:
                continue
            for eid, what_a, what_b in _clashes(effects[id(first)], effects[id(second)]):
                certain = not first.conditions and not second.conditions
                trigger = sigs[id(second)][sorted(shared)[0]]
                ctx.add("contradictory-automations", second.file, trigger.line,
                        f"{first.where} ({first.file}, line {first.line}) sets {eid} to {what_a}, and {second.where} sets it to {what_b}, from the same trigger."
                        + ("" if certain else " One of them has conditions, so check they can't both pass at once."),
                        second.where, severity=ERROR if certain else WARNING)
                break


def _fixed_times(a: Automation) -> list[int]:
    out = []
    for trigger in a.triggers:
        if trigger_type(trigger) == "time" and not is_disabled(trigger):
            for value in trigger.get("at") if isinstance(trigger.get("at"), list) else [trigger.get("at")]:
                seconds = parse_clock(value) if isinstance(value, str) else None
                if seconds is not None:
                    out.append(seconds)
    return out


def _time_clash(ctx: Ctx, autos: list[Automation], effects: dict[int, dict]) -> None:
    times = {id(a): _fixed_times(a) for a in autos}
    for i, first in enumerate(autos):
        for second in autos[i + 1:]:
            close = [(t1, t2) for t1 in times[id(first)] for t2 in times[id(second)] if t1 != t2 and abs(t1 - t2) <= 60]
            if not close:
                continue
            clashes = _clashes(effects[id(first)], effects[id(second)])
            if clashes:
                eid, what_a, what_b = clashes[0]
                t1, t2 = close[0]
                ctx.add("time-clash", second.file, second.line,
                        f"{first.where} sets {eid} to {what_a} at {clock_text(t1)}:{t1 % 60:02d} and {second.where} sets it to {what_b} at {clock_text(t2)}:{t2 % 60:02d}.",
                        second.where)


def _location(ctx: Ctx) -> tuple[float, float, str | None] | None:
    core = ctx.cs.config.get("homeassistant") if isinstance(ctx.cs.config, LMap) else None
    if isinstance(core, LMap):
        lat, lon, tz = core.get("latitude"), core.get("longitude"), core.get("time_zone")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and not isinstance(lat, bool):
            return (round(float(lat), 1), round(float(lon), 1), tz if isinstance(tz, str) else None)
    return ctx.reg.location


def _has_time_guard(a: Automation) -> bool:
    return any(condition_type(c) in ("time", "sun") or (isinstance(c, LMap) and c.get("entity_id") == "sun.sun") for c in a.conditions)


def _sun_overlap(ctx: Ctx, autos: list[Automation], effects: dict[int, dict]) -> None:
    location = _location(ctx)
    ranges = yearly_ranges(location)
    sure = location is not None
    sun_events: list[tuple[Automation, str, int, int]] = []
    for a in autos:
        for trigger in a.triggers:
            if trigger_type(trigger) == "sun" and not is_disabled(trigger) and trigger.get("event") in ranges:
                offset = duration_seconds(trigger.get("offset")) or 0 if "offset" in trigger else 0
                low, high = ranges[trigger["event"]]
                sun_events.append((a, trigger["event"], int(low + offset), int(high + offset)))
    times = {id(a): _fixed_times(a) for a in autos}
    reported: set[tuple[int, int]] = set()
    for sun_auto, event, low, high in sun_events:
        for other in autos:
            if other is sun_auto or (id(sun_auto), id(other)) in reported or _has_time_guard(other) or _has_time_guard(sun_auto):
                continue
            for fixed in times[id(other)]:
                if low < fixed < high:
                    clashes = _clashes(effects[id(sun_auto)], effects[id(other)])
                    if not clashes:
                        continue
                    eid, what_sun, what_fixed = clashes[0]
                    reported.add((id(sun_auto), id(other)))
                    ctx.add("sun-time-overlap", other.file, other.line,
                            f"{sun_auto.where} sets {eid} to {what_sun} at {event}, which "
                            + ("moves between " if sure else "may move between ")
                            + f"about {clock_text(low)} and {clock_text(high)} through the year. "
                            f"{other.where} sets it to {what_fixed} at {clock_text(fixed)}, so on some days the order is swapped."
                            + ("" if sure else " (Your home location wasn't found, so this uses typical sunrise and sunset times.)"),
                            other.where)
                    break
