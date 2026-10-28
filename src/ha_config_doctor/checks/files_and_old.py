"""File-level checks (passwords typed into files, blueprints) and retired integrations and options."""

from __future__ import annotations

from typing import Any

from ..catalog import ERROR, WARNING
from ..redact import is_sensitive_key
from ..util import as_list, is_template
from ..yamlio import HATag, LList, LMap
from .common import Ctx, iter_steps

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
    _retired_integrations(ctx)
    _retired_options(ctx)
    _retired_in_steps(ctx)
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


# ------------------------------------------------------------------ retired integrations

REMOVED_INTEGRATIONS = {
    "zwave": "The old Z-Wave integration was removed. Use Z-Wave JS (Settings > Devices & services).",
    "ozw": "The OpenZWave integration was removed. Use Z-Wave JS (Settings > Devices & services).",
    "introduction": "The introduction card was removed long ago. Delete this line.",
    "discovery": "The old discovery integration was removed; Home Assistant now finds devices by itself. Delete this line.",
    "updater": "The updater integration was replaced by update entities and the Version integration. Delete this line.",
}
DEPRECATED_INTEGRATIONS = {
    "map": "The map: line is no longer needed; add a Map card to a dashboard instead.",
}
PLATFORMS_MOVED_TO_UI = {
    "ping": "Ping", "systemmonitor": "System Monitor", "time_date": "Time & Date", "workday": "Workday",
    "uptime": "Uptime", "version": "Version", "season": "Season", "moon": "Moon",
    "google_translate": "Google Translate text-to-speech",
}
PLATFORMS_REMOVED = {
    "mqtt": "Writing MQTT entities as platform: mqtt was removed. Put them under the mqtt: section instead (mqtt: > sensor: > - name: …).",
    "command_line": "Writing command line entities as platform: command_line was removed. Put them under the command_line: section instead.",
}


def _retired_integrations(ctx: Ctx) -> None:
    for domain, sections in ctx.model.sections.items():
        for section in sections:
            if domain in REMOVED_INTEGRATIONS:
                ctx.add("removed-integration", section.file, section.line, f'"{section.key}:" — {REMOVED_INTEGRATIONS[domain]}')
            elif domain in DEPRECATED_INTEGRATIONS:
                ctx.add("deprecated-integration", section.file, section.line, f'"{section.key}:" — {DEPRECATED_INTEGRATIONS[domain]}')
    for domain, item, _package in ctx.model.platform_entries:
        platform = item.get("platform")
        where = f'"{domain}:" section'
        if platform == "template":
            ctx.add("legacy-template-entity", item.file, item.key_line("platform"),
                    f"{domain}: > platform: template is the old style.", where)
            plural = {"sensor": "sensors", "binary_sensor": "sensors"}.get(domain)
            named = item.get(plural) if plural else None
            if isinstance(named, LMap):
                for key, entity in named.items():
                    if isinstance(entity, LMap) and "entity_id" in entity:
                        ctx.add("deprecated-option", entity.file, entity.key_line("entity_id"),
                                "entity_id: inside a template sensor was removed years ago; Home Assistant now works out what to watch by itself.",
                                where, severity=ERROR, fix="Delete the entity_id: line.")
        elif platform in PLATFORMS_REMOVED:
            ctx.add("removed-integration", item.file, item.key_line("platform"), PLATFORMS_REMOVED[platform], where)
        elif platform in PLATFORMS_MOVED_TO_UI:
            ctx.add("deprecated-integration", item.file, item.key_line("platform"),
                    f'{domain}: > platform: {platform} — {PLATFORMS_MOVED_TO_UI[platform]} is now set up in the screens '
                    f'(Settings > Devices & services > Add integration > {PLATFORMS_MOVED_TO_UI[platform]}). YAML set-up has been retired.', where)
        if "entity_namespace" in item:
            ctx.add("deprecated-option", item.file, item.key_line("entity_namespace"),
                    "entity_namespace: was removed.", where, severity=ERROR, fix="Delete the entity_namespace: line.")


# ------------------------------------------------------------------ retired options

_SECTION_OPTIONS = {
    ("homeassistant", "whitelist_external_dirs"): (WARNING, "whitelist_external_dirs: was renamed.", "Rename it to allowlist_external_dirs:."),
    ("homeassistant", "legacy_templates"): (ERROR, "legacy_templates: was removed.", "Delete the line."),
    ("http", "base_url"): (ERROR, "base_url: was removed from http:.", "Set the addresses under Settings > System > Network, then delete the line."),
    ("http", "api_password"): (ERROR, "api_password: was removed (and the value here is hidden).", "Delete the line; use normal logins or long-lived tokens instead."),
    ("http", "trusted_networks"): (ERROR, "trusted_networks: no longer belongs under http:.", "Use the trusted_networks auth provider under homeassistant: auth_providers:."),
    ("recorder", "purge_interval"): (ERROR, "purge_interval: was removed from recorder:.", "Use auto_purge: true (the default) and purge_keep_days:."),
    ("frontend", "javascript_version"): (ERROR, "javascript_version: was removed from frontend:.", "Delete the line."),
}
_MQTT_BROKER_OPTIONS = ("broker", "port", "username", "password", "client_id", "keepalive", "certificate",
                        "client_key", "client_cert", "tls_insecure", "protocol", "discovery", "discovery_prefix", "birth_message", "will_message")


def _retired_options(ctx: Ctx) -> None:
    for (domain, option), (severity, text, fix) in _SECTION_OPTIONS.items():
        for section in ctx.model.section_list(domain):
            if isinstance(section.value, LMap) and option in section.value:
                ctx.add("deprecated-option", section.value.file, section.value.key_line(option), f"{domain}: > {text}",
                        f'"{section.key}:" section', severity=severity, fix=fix)
    for section in ctx.model.section_list("mqtt"):
        if isinstance(section.value, LMap):
            found = [o for o in _MQTT_BROKER_OPTIONS if o in section.value]
            if found:
                ctx.add("deprecated-option", section.value.file, section.value.key_line(found[0]),
                        f"mqtt: > {', '.join(found)}: — connection settings for MQTT are no longer read from YAML.",
                        '"mqtt:" section', severity=ERROR,
                        fix="Set the connection in Settings > Devices & services > MQTT > Configure, then delete these lines.")
    for automation in ctx.model.automations:
        if "hide_entity" in automation.raw:
            ctx.add("deprecated-option", automation.file, automation.raw.key_line("hide_entity"),
                    "hide_entity: was removed, and Home Assistant now rejects automations that have it.",
                    automation.where, severity=ERROR, fix="Delete the hide_entity: line.")


_STEP_OPTIONS = {
    "white_value": (ERROR, "white_value was removed from lights.", "Use white: or rgbw_color: instead."),
    "color_temp": (WARNING, "color_temp (in mireds) has been retired for lights.", "Use color_temp_kelvin: instead (kelvin = 1,000,000 ÷ mireds)."),
    "kelvin": (WARNING, "kelvin: has been retired for lights.", "Use color_temp_kelvin: instead."),
}
_REMOVED_ACTIONS = {
    "weather.get_forecast": "weather.get_forecast was removed. Use weather.get_forecasts (with an s), whose result is grouped by entity.",
    "climate.set_aux_heat": "climate.set_aux_heat was removed (\"auxiliary heat\" is no longer part of climate devices).",
    "group.set_visibility": "group.set_visibility was removed long ago.",
}


def _retired_in_steps(ctx: Ctx) -> None:
    for where, actions, owner in ctx.model.iter_action_lists():
        for step in iter_steps(actions):
            item = step.step
            if step.kind != "call_service" or not isinstance(item, LMap):
                continue
            service = item.get("action", item.get("service"))
            key = "action" if "action" in item else "service"
            if isinstance(service, str) and service in _REMOVED_ACTIONS:
                ctx.add("deprecated-option", item.file, item.key_line(key), _REMOVED_ACTIONS[service], where, severity=ERROR)
            if isinstance(service, str) and service.startswith("light."):
                data = item.get("data", item.get("data_template"))
                if isinstance(data, LMap):
                    for option, (severity, text, fix) in _STEP_OPTIONS.items():
                        if option in data:
                            ctx.add("deprecated-option", data.file, data.key_line(option), text, where, severity=severity, fix=fix)


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
