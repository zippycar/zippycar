"""Checks on templates: typing mistakes and templates that break when a device is unavailable."""

from __future__ import annotations

from ..templates import TRIGGER_STATE_ONLY_ATTRS, analyse
from ..util import quote_list
from .common import STATE_LIKE_TRIGGERS, Ctx, is_disabled, trigger_type
from .references import entity_status, did_you_mean

LOOKUP_FUNCTIONS = {"states", "is_state", "state_attr", "is_state_attr", "has_value", "states.", "states[]"}


def run(ctx: Ctx) -> None:
    for use in ctx.model.templates:
        info = analyse(str(use.text))
        where = use.owner
        if info.syntax_error:
            lineno, message = info.syntax_error
            ctx.add("template-syntax-error", use.file, use.line + lineno - 1, f"The template can't be read here (technical detail: {message}).", where)
            continue
        if info.no_default:
            ctx.add("template-no-default", use.file, use.line,
                    f"Uses {quote_list(sorted(set(info.no_default)))} without a fallback value.", where)
        if info.text_number_compare:
            ctx.add("template-text-number-compare", use.file, use.line,
                    "A state (which is text) is compared with a number.", where)
        for entity in sorted(set(info.direct_state)):
            ctx.add("template-direct-state", use.file, use.line,
                    f"Uses states.{entity}… directly.", where, fix=f"Use states('{entity}') instead.")
        automation = use.automation
        if automation is not None and info.trigger_attrs & TRIGGER_STATE_ONLY_ATTRS and not info.trigger_guarded and not use.in_trigger_branch:
            other = sorted({trigger_type(t) or "?" for t in automation.triggers
                            if not is_disabled(t) and trigger_type(t) not in STATE_LIKE_TRIGGERS})
            if other:
                used = ", ".join(f"trigger.{name}" for name in sorted(info.trigger_attrs & TRIGGER_STATE_ONLY_ATTRS))
                ctx.add("trigger-data-mismatch", use.file, use.line,
                        f"Uses {used}, but the automation can also be started by a {quote_list(other)} trigger, which doesn't have it.",
                        automation.where)
        for entity, how in info.entity_refs:
            if how not in LOOKUP_FUNCTIONS:
                continue
            status, extra = entity_status(ctx, entity)
            if status == "retired":
                ctx.add("template-missing-entity", use.file, use.line,
                        f"{how.rstrip('.[]') or 'states'}('{entity}') — {extra}", where)
            elif status == "missing" and ctx.reg.has_entities:
                ctx.add("template-missing-entity", use.file, use.line,
                        f"{how.rstrip('.[]') or 'states'}('{entity}') — there is no entity called {entity}.{did_you_mean(ctx, entity)}", where)
