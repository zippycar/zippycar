"""Removed, retired and changed features, driven entirely by the rules in data/ha_rules.yaml."""

from __future__ import annotations

from fnmatch import fnmatchcase
from typing import Any

from ..model import Automation, Script
from ..rules import Rule, fix_for, judge, legacy_template_replacement
from ..templates import analyse
from ..util import as_list
from ..yamlio import LMap
from .common import Ctx, iter_steps

CODES = {
    "integration": "retired-integration",
    "platform": "retired-integration",
    "option": "retired-setting",
    "platform_option": "retired-setting",
    "automation_option": "retired-setting",
    "template_attribute": "retired-setting",
    "action": "retired-action",
    "action_data": "retired-action",
    "changed": "behaviour-change",
    "legacy_template": "legacy-template-entity",
}


def run(ctx: Ctx) -> None:
    for rule in ctx.rules.rules:
        HANDLERS[rule.kind](ctx, rule)


def _emit(ctx: Ctx, rule: Rule, file: str, line: int, detail: str, where: str = "", example: str = "") -> None:
    verdict = judge(rule, ctx.version.parts)
    ctx.add(CODES[rule.kind], file, line, f"{detail} {rule.explanation}", where, fix=fix_for(rule, ctx.version.parts),
            severity=verdict.severity, rule_id=rule.id, when=verdict.when, source=rule.source,
            provenance=rule.provenance(), example=example)


def _names(rule: Rule, key: str) -> list[str]:
    return [str(x) for x in as_list(rule.match.get(key))]


def _section_where(section: Any) -> str:
    return f'Package "{section.package}"' if section.package else ""


def _integration(ctx: Ctx, rule: Rule) -> None:
    names = set(_names(rule, "names"))
    for name in sorted(names):
        for section in ctx.model.section_list(name):
            _emit(ctx, rule, section.file, section.line, f'The "{section.key}:" section.', _section_where(section))
    for domain, item, _package in ctx.model.platform_entries:
        if item.get("platform") in names:
            _emit(ctx, rule, item.file, item.key_line("platform"), f"{domain}: > platform: {item.get('platform')}.", f'"{domain}:" section')


def _platform(ctx: Ctx, rule: Rule) -> None:
    platforms = set(_names(rule, "platforms"))
    domains = set(_names(rule, "domains"))
    for domain, item, _package in ctx.model.platform_entries:
        if item.get("platform") in platforms and (not domains or domain in domains):
            _emit(ctx, rule, item.file, item.key_line("platform"), f"{domain}: > platform: {item.get('platform')}.", f'"{domain}:" section')


def _option(ctx: Ctx, rule: Rule) -> None:
    section_name = str(rule.match.get("section"))
    options = _names(rule, "options")
    for section in ctx.model.section_list(section_name):
        if isinstance(section.value, LMap):
            found = [o for o in options if o in section.value]
            if found:
                listed = ", ".join(f'"{o}"' for o in found)
                _emit(ctx, rule, section.value.file, section.value.key_line(found[0]),
                      f'In "{section.key}:", the {listed} setting{"s" if len(found) > 1 else ""}.',
                      _section_where(section) or f'"{section.key}:" section')


def _platform_option(ctx: Ctx, rule: Rule) -> None:
    options = _names(rule, "options")
    platforms = set(_names(rule, "platforms"))
    for domain, item, _package in ctx.model.platform_entries:
        if platforms and item.get("platform") not in platforms:
            continue
        for option in options:
            if option in item:
                _emit(ctx, rule, item.file, item.key_line(option), f'{domain}: > platform: {item.get("platform")} has the "{option}" setting.', f'"{domain}:" section')


def _automation_option(ctx: Ctx, rule: Rule) -> None:
    for automation in ctx.model.automations:
        for option in _names(rule, "options"):
            if option in automation.raw:
                _emit(ctx, rule, automation.file, automation.raw.key_line(option), f'The automation has the "{option}" setting.', automation.where)


def _service_steps(ctx: Ctx, patterns: list[str], contexts: list[str] | None = None):
    for automation in ctx.model.automations:
        if contexts and "automation" not in contexts:
            break
        yield from _matching_steps(automation, automation.actions, patterns)
    for script in ctx.model.scripts:
        if contexts and "script" not in contexts:
            break
        yield from _matching_steps(script, script.actions, patterns)


def _matching_steps(owner: Automation | Script, actions: list, patterns: list[str]):
    for step in iter_steps(actions):
        item = step.step
        if step.kind != "call_service" or not isinstance(item, LMap):
            continue
        key = next((k for k in ("action", "service", "service_template") if k in item), None)
        service = item.get(key) if key else None
        if isinstance(service, str) and any(fnmatchcase(service.strip(), p) for p in patterns):
            yield owner, item, key, service.strip()


def _action(ctx: Ctx, rule: Rule) -> None:
    for owner, item, key, service in _service_steps(ctx, _names(rule, "actions")):
        _emit(ctx, rule, item.file, item.key_line(key), f"This step uses {service}.", owner.where)


def _action_data(ctx: Ctx, rule: Rule) -> None:
    options = _names(rule, "data")
    for owner, item, _key, service in _service_steps(ctx, _names(rule, "actions")):
        for holder in (item.get("data"), item.get("data_template"), item):
            if isinstance(holder, LMap):
                for option in options:
                    if option in holder:
                        _emit(ctx, rule, holder.file, holder.key_line(option), f'{service} is given the "{option}" option.', owner.where)


def _changed(ctx: Ctx, rule: Rule) -> None:
    contexts = _names(rule, "contexts") or ["automation", "script"]
    for owner, item, key, service in _service_steps(ctx, _names(rule, "actions"), contexts):
        _emit(ctx, rule, item.file, item.key_line(key), f"This step uses {service}.", owner.where)


def _template_attribute(ctx: Ctx, rule: Rule) -> None:
    domains = set(_names(rule, "domains"))
    attributes = set(_names(rule, "attributes"))
    for use in ctx.model.templates:
        for entity, attribute in analyse(str(use.text)).attribute_refs:
            if entity.split(".", 1)[0] in domains and attribute in attributes:
                _emit(ctx, rule, use.file, use.line, f'The template reads the "{attribute}" detail of {entity}.', use.owner)


def _legacy_template(ctx: Ctx, rule: Rule) -> None:
    domains = set(_names(rule, "domains"))
    for domain, item, _package in ctx.model.platform_entries:
        if item.get("platform") == "template" and domain in domains:
            example = legacy_template_replacement(domain, item, ctx.rules.conversion)
            _emit(ctx, rule, item.file, item.key_line("platform"), f"{domain}: > platform: template is the old way of writing template entities.",
                  f'"{domain}:" section', example=example)


HANDLERS = {
    "integration": _integration,
    "platform": _platform,
    "option": _option,
    "platform_option": _platform_option,
    "automation_option": _automation_option,
    "action": _action,
    "action_data": _action_data,
    "changed": _changed,
    "template_attribute": _template_attribute,
    "legacy_template": _legacy_template,
}
