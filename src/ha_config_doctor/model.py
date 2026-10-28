"""Turn the configuration files into a list of automations, scripts, helpers and entity names.

Also collects every place an entity is mentioned (in ``entity_id:``, targets,
templates, dashboards …) so the reference checks can cross-check them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Iterator

from .catalog import Findings
from .configtree import ConfigSet
from .registry import Registry
from .rules import Rule, RuleBook, judge
from .templates import analyse
from .util import (
    HELPER_DOMAINS, KNOWN_DOMAINS, REGISTRY_ID_RE, as_list, entity_ids_in, is_template,
    looks_like_known_entity, slugify,
)
from .yamlio import HATag, LList, LMap, LStr

TEMPLATE_ENTITY_DOMAINS = (
    "sensor", "binary_sensor", "button", "image", "light", "lock", "number", "select", "switch",
    "weather", "fan", "cover", "vacuum", "alarm_control_panel", "event", "update", "device_tracker",
)
LEGACY_TEMPLATE_KEYS = {
    "sensor": "sensors", "binary_sensor": "sensors", "switch": "switches", "light": "lights",
    "cover": "covers", "fan": "fans", "lock": None, "vacuum": "vacuums",
    "alarm_control_panel": "panels", "weather": None,
}
PLATFORM_DOMAINS = {
    "sensor", "binary_sensor", "switch", "light", "cover", "fan", "lock", "climate", "media_player",
    "camera", "weather", "device_tracker", "notify", "tts", "alarm_control_panel", "vacuum", "remote",
    "water_heater", "humidifier", "image_processing", "geo_location", "air_quality", "calendar",
    "siren", "number", "select", "button", "text", "valve", "event", "stt", "todo",
}
# YAML integrations that create entities in ways we can't predict the names of.
UNPREDICTABLE_YAML = {"modbus", "knx", "rflink", "enocean", "lcn", "homematic", "tellstick", "ads", "pilight", "mysensors"}

ENTITY_KEYS = {"entity_id", "entities", "entity", "entity_ids"}
NOT_ENTITY_KEYS = {
    "id", "alias", "name", "description", "unique_id", "icon", "platform", "trigger", "condition",
    "event", "event_type", "default_entity_id", "object_id", "source_url", "path", "url", "filename",
    "friendly_name", "mode", "domain", "type", "device_class", "unit_of_measurement", "state_class",
    "entity_category", "topic", "title", "max_exceeded", "attribute", "option", "options",
}
SCRIPT_BUILTIN_SERVICES = {"script.turn_on", "script.turn_off", "script.toggle", "script.reload"}
BUILTIN_ENTITIES = {"zone.home", "sun.sun"}


@dataclass
class Section:
    domain: str
    key: str
    value: Any
    file: str
    line: int
    package: str | None


@dataclass
class Definition:
    entity_id: str
    file: str
    line: int
    how: str  # "yaml", "storage", "registry", "builtin"


def _first(mapping: LMap, *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def flatten_triggers(value: Any) -> list:
    out: list = []
    for item in as_list(value):
        if isinstance(item, LMap) and "triggers" in item and not ("trigger" in item or "platform" in item):
            out.extend(flatten_triggers(item["triggers"]))
        else:
            out.append(item)
    return out


class Automation:
    def __init__(self, raw: LMap, number: int, package: str | None) -> None:
        self.raw = raw
        self.number = number
        self.package = package
        self.file = raw.file
        self.line = raw.line
        self.entity_id: str | None = None

    @property
    def alias(self) -> str | None:
        value = self.raw.get("alias")
        return str(value) if isinstance(value, str) and value.strip() else None

    @property
    def id(self) -> str | None:
        value = self.raw.get("id")
        if value is None or isinstance(value, (dict, list)):
            return None
        return str(value)

    @property
    def where(self) -> str:
        if self.alias:
            return f'Automation "{self.alias}"'
        if self.id:
            return f'Automation with id "{self.id}"'
        return f"Automation number {self.number}"

    @property
    def triggers(self) -> list:
        return flatten_triggers(_first(self.raw, "triggers", "trigger"))

    @property
    def conditions(self) -> list:
        return as_list(_first(self.raw, "conditions", "condition"))

    @property
    def actions(self) -> list:
        return as_list(_first(self.raw, "actions", "action"))

    @property
    def mode(self) -> str:
        value = self.raw.get("mode", "single")
        return str(value) if isinstance(value, str) else "single"

    @property
    def blueprint(self) -> LMap | None:
        value = self.raw.get("use_blueprint")
        return value if isinstance(value, LMap) else None

    def key_line(self, key: str) -> int:
        return self.raw.key_line(key)


class Script:
    def __init__(self, key: str, raw: LMap, file: str, line: int, package: str | None) -> None:
        self.key = key
        self.raw = raw
        self.file = file
        self.line = line
        self.package = package

    @property
    def where(self) -> str:
        return f'Script "{self.key}"'

    @property
    def actions(self) -> list:
        return as_list(self.raw.get("sequence"))

    @property
    def mode(self) -> str:
        value = self.raw.get("mode", "single")
        return str(value) if isinstance(value, str) else "single"


@dataclass
class Ref:
    entity_id: str
    file: str
    line: int
    kind: str  # entity, template, string, script-call, scene, zone, registry-id, customize, dashboard
    owner: str
    role: str  # trigger, condition, action, other
    how: str = ""  # for templates: the function used (is_state, states …)


@dataclass
class TemplateUse:
    text: str
    file: str
    line: int  # line where the template's text starts
    key: Any
    owner: str
    role: str
    automation: Automation | None
    parent: Any = None
    in_trigger_branch: bool = False


@dataclass
class ServiceRef:
    name: str
    file: str
    line: int
    owner: str


@dataclass
class DeviceRef:
    device_id: str
    file: str
    line: int
    owner: str


@dataclass
class Model:
    config: ConfigSet
    registry: Registry
    findings: Findings
    rules: RuleBook | None = None
    version: tuple[int, int, int] | None = None
    sections: dict[str, list[Section]] = field(default_factory=dict)
    automations: list[Automation] = field(default_factory=list)
    scripts: list[Script] = field(default_factory=list)
    scenes: list[LMap] = field(default_factory=list)
    helpers: dict[str, Definition] = field(default_factory=dict)
    defined: dict[str, Definition] = field(default_factory=dict)
    services: set[str] = field(default_factory=set)
    unpredictable_domains: set[str] = field(default_factory=set)
    platform_entries: list[tuple[str, LMap, str | None]] = field(default_factory=list)
    named_collections: list[LMap] = field(default_factory=list)
    refs: list[Ref] = field(default_factory=list)
    templates: list[TemplateUse] = field(default_factory=list)
    service_refs: list[ServiceRef] = field(default_factory=list)
    device_refs: list[DeviceRef] = field(default_factory=list)
    # entities that only came from something Home Assistant has removed (for the version checked)
    retired_defined: dict[str, tuple[Definition, Rule]] = field(default_factory=dict)
    _retiring: Rule | None = None

    # ------------------------------------------------------------------ building
    def build(self) -> "Model":
        self._collect_sections()
        self._collect_automations()
        self._collect_scripts()
        self._collect_scenes()
        self._collect_helpers_and_entities()
        self._collect_refs()
        return self

    def section_list(self, domain: str) -> list[Section]:
        return self.sections.get(domain, [])

    def _add_section(self, key: Any, value: Any, container: LMap, package: str | None) -> None:
        if not isinstance(key, str):
            return
        domain = key.split(" ", 1)[0]
        self.sections.setdefault(domain, []).append(
            Section(domain, key, value, container.file, container.key_line(key), package)
        )

    def _collect_sections(self) -> None:
        config = self.config.config
        for key, value in config.items():
            self._add_section(key, value, config, None)
        core = config.get("homeassistant")
        packages = core.get("packages") if isinstance(core, LMap) else None
        if isinstance(packages, LMap):
            for name, package in packages.items():
                if isinstance(package, LMap):
                    for key, value in package.items():
                        self._add_section(key, value, package, str(name))

    def _wrong_shape(self, section: Section, expected: str) -> None:
        self.findings.add("wrong-include-type", section.file, section.line,
                          f'The "{section.key}" section should be {expected}, but it isn\'t.')

    def _collect_automations(self) -> None:
        number = 0
        for section in self.section_list("automation"):
            value = section.value
            if value is None or (isinstance(value, LMap) and not value):
                continue
            if isinstance(value, LList):
                items = list(value)
            elif isinstance(value, LMap) and any(k in value for k in ("trigger", "triggers", "action", "actions", "use_blueprint", "alias", "id")):
                items = [value]
            else:
                self._wrong_shape(section, "a list of automations (each starting with a dash)")
                continue
            for index, item in enumerate(items):
                if not isinstance(item, LMap):
                    line = value.item_line(index) if isinstance(value, LList) else section.line
                    self.findings.add("wrong-include-type", getattr(value, "file", section.file), line,
                                      "This item in the automation list isn't an automation (a block of settings).")
                    continue
                number += 1
                self.automations.append(Automation(item, number, section.package))

    def _collect_scripts(self) -> None:
        for section in self.section_list("script"):
            value = section.value
            if value is None:
                continue
            if not isinstance(value, LMap):
                self._wrong_shape(section, "a set of named scripts")
                continue
            self.named_collections.append(value)
            for key, cfg in value.items():
                if isinstance(cfg, LMap):
                    self.scripts.append(Script(str(key), cfg, cfg.file or value.file, cfg.line or value.key_line(key), section.package))
                    self.services.add(f"script.{key}")

    def _collect_scenes(self) -> None:
        for section in self.section_list("scene"):
            value = section.value
            items = list(value) if isinstance(value, LList) else [value] if isinstance(value, LMap) and value else []
            if value is not None and not isinstance(value, (LList, LMap)):
                self._wrong_shape(section, "a list of scenes")
            for item in items:
                if isinstance(item, LMap) and "platform" not in item:
                    self.scenes.append(item)

    def _define(self, entity_id: str, file: str, line: int, how: str = "yaml") -> None:
        if self._retiring is not None:
            self.retired_defined.setdefault(entity_id, (Definition(entity_id, file, line, how), self._retiring))
            return
        self.defined.setdefault(entity_id, Definition(entity_id, file, line, how))

    def removed_platform_rule(self, domain: str, platform: Any) -> Rule | None:
        """The rule that says this platform no longer exists in the version being checked, if any."""

        if self.rules is None or self.version is None or not isinstance(platform, str):
            return None
        for rule in self.rules.rules:
            match = rule.match
            hit = (
                (rule.kind == "legacy_template" and platform == "template" and domain in as_list(match.get("domains")))
                or (rule.kind == "platform" and platform in as_list(match.get("platforms"))
                    and (not match.get("domains") or domain in as_list(match.get("domains"))))
                or (rule.kind == "integration" and platform in as_list(match.get("names")))
            )
            if hit and judge(rule, self.version).status == "removed":
                return rule
        return None

    def _collect_helpers_and_entities(self) -> None:
        reg = self.registry
        for domain in HELPER_DOMAINS:
            for section in self.section_list(domain):
                if isinstance(section.value, LMap):
                    self.named_collections.append(section.value)
                    for key in section.value:
                        eid = f"{domain}.{key}"
                        self.helpers[eid] = Definition(eid, section.value.file, section.value.key_line(key), "yaml")
                        self._define(eid, section.value.file, section.value.key_line(key))
                elif section.value is not None:
                    self._wrong_shape(section, "a set of named helpers")
        for domain, ids in reg.helper_ids.items():
            for object_id in ids:
                eid = f"{domain}.{object_id}"
                if domain in HELPER_DOMAINS:
                    self.helpers.setdefault(eid, Definition(eid, "", 0, "storage"))
                self._define(eid, "", 0, "storage")
        for eid, entity in reg.entities.items():
            domain = eid.split(".", 1)[0]
            if domain in HELPER_DOMAINS and entity.platform == domain and not entity.disabled_by:
                self.helpers.setdefault(eid, Definition(eid, "", 0, "registry"))

        for automation in self.automations:
            derived = set()
            if automation.id and reg.has_entities:
                actual = reg.by_unique.get(("automation", automation.id))
                if actual:
                    derived.add(actual)
            if automation.alias:
                derived.add(f"automation.{slugify(automation.alias)}")
            elif automation.id:
                derived.add(f"automation.{slugify(automation.id)}")
            automation.entity_id = sorted(derived)[0] if derived else None
            for eid in derived:
                self._define(eid, automation.file, automation.line)
        for script in self.scripts:
            self._define(f"script.{slugify(script.key)}", script.file, script.line)
            actual = reg.by_unique.get(("script", script.key))
            if actual:
                self._define(actual, script.file, script.line)
        for scene in self.scenes:
            name, scene_id = scene.get("name"), scene.get("id")
            if isinstance(name, str):
                self._define(f"scene.{slugify(name)}", scene.file, scene.line)
            if scene_id is not None:
                actual = reg.by_unique.get(("homeassistant", str(scene_id)))
                if actual:
                    self._define(actual, scene.file, scene.line)

        simple_named = {"group": "group", "alert": "alert", "plant": "plant", "utility_meter": "sensor", "proximity": "proximity"}
        for domain, entity_domain in simple_named.items():
            for section in self.section_list(domain):
                if isinstance(section.value, LMap):
                    if domain in ("group",):
                        self.named_collections.append(section.value)
                    for key in section.value:
                        self._define(f"{entity_domain}.{key}", section.value.file, section.value.key_line(key))
        for domain in ("shell_command", "rest_command"):
            for section in self.section_list(domain):
                if isinstance(section.value, LMap):
                    self.named_collections.append(section.value)
                    for key in section.value:
                        self.services.add(f"{domain}.{key}")
        if self.section_list("python_script"):
            folder = self.config.root / "python_scripts"
            if folder.is_dir():
                for name in os.listdir(folder):
                    if name.endswith(".py"):
                        self.services.add(f"python_script.{name[:-3]}")
        for section in self.section_list("zone"):
            for item in as_list(section.value):
                if isinstance(item, LMap) and isinstance(item.get("name"), str):
                    self._define(f"zone.{slugify(item['name'])}", item.file, item.line)
        for section in self.section_list("person"):
            for item in as_list(section.value):
                if isinstance(item, LMap) and item.get("id") is not None:
                    self._define(f"person.{item['id']}", item.file, item.line)
        for name in self.config.known_device_names:
            self._define(f"device_tracker.{name}", "known_devices.yaml", 0)
        for eid in BUILTIN_ENTITIES:
            self._define(eid, "", 0, "builtin")

        self._collect_template_entities()
        self._collect_platform_entities()
        for domain in UNPREDICTABLE_YAML:
            if self.section_list(domain):
                self.unpredictable_domains |= {"sensor", "binary_sensor", "switch", "light", "cover", "climate", "fan"}

    def _entity_from_config(self, domain: str, item: LMap) -> None:
        default_id = item.get("default_entity_id")
        if isinstance(default_id, str) and "." in default_id:
            self._define(default_id, item.file, item.line)
            return
        object_id = item.get("object_id")
        if isinstance(object_id, str) and object_id:
            self._define(f"{domain}.{object_id}", item.file, item.line)
            return
        name = item.get("name")
        if isinstance(name, str) and name and not is_template(name) and "device" not in item:
            self._define(f"{domain}.{slugify(name)}", item.file, item.line)
        elif self._retiring is None:
            self.unpredictable_domains.add(domain)

    def _collect_template_entities(self) -> None:
        for section in self.section_list("template"):
            for block in as_list(section.value):
                if not isinstance(block, LMap):
                    continue
                for domain in TEMPLATE_ENTITY_DOMAINS:
                    for item in as_list(block.get(domain)):
                        if isinstance(item, LMap):
                            self._entity_from_config(domain, item)

    def _collect_platform_entities(self) -> None:
        for domain in PLATFORM_DOMAINS:
            for section in self.section_list(domain):
                for item in as_list(section.value):
                    if not isinstance(item, LMap):
                        continue
                    platform = item.get("platform")
                    if isinstance(platform, str):
                        self.platform_entries.append((domain, item, section.package))
                    self._retiring = self.removed_platform_rule(domain, platform)
                    self._platform_entity(domain, item, platform)
                    self._retiring = None
        self._collect_yaml_integration_entities()

    def _platform_entity(self, domain: str, item: LMap, platform: Any) -> None:
        if platform == "template":
            plural = LEGACY_TEMPLATE_KEYS.get(domain)
            named = item.get(plural) if plural else None
            if isinstance(named, LMap):
                for key in named:
                    self._define(f"{domain}.{key}", named.file, named.key_line(key))
            else:
                self._entity_from_config(domain, item)
        elif domain == "notify":
            name = item.get("name")
            self.services.add(f"notify.{slugify(name) if isinstance(name, str) else 'notify'}")
        elif domain not in ("tts", "stt"):
            self._entity_from_config(domain, item)

    def _collect_yaml_integration_entities(self) -> None:
        for section in self.section_list("mqtt"):
            if isinstance(section.value, LMap):
                for domain, items in section.value.items():
                    if domain in KNOWN_DOMAINS:
                        for item in as_list(items):
                            if isinstance(item, LMap):
                                self._entity_from_config(str(domain), item)
            elif isinstance(section.value, LList):
                for entry in section.value:
                    if isinstance(entry, LMap):
                        for domain, item in entry.items():
                            if domain in KNOWN_DOMAINS and isinstance(item, LMap):
                                self._entity_from_config(str(domain), item)
        for name in ("command_line", "rest", "scrape", "sql"):
            for section in self.section_list(name):
                for entry in as_list(section.value):
                    if not isinstance(entry, LMap):
                        continue
                    for domain, items in entry.items():
                        if domain in KNOWN_DOMAINS:
                            for item in as_list(items):
                                if isinstance(item, LMap):
                                    self._entity_from_config(str(domain), item)
                    if name == "sql" and "name" in entry:
                        self._entity_from_config("sensor", entry)

    # ------------------------------------------------------------------ known entities
    def entity_known(self, entity_id: str) -> bool:
        reg = self.registry
        return (
            entity_id in reg.entities
            or entity_id in self.defined
            or (reg.restore is not None and entity_id in reg.restore)
        )

    def all_known_entities(self) -> set[str]:
        known = set(self.registry.entities) | set(self.defined)
        if self.registry.restore:
            known |= set(self.registry.restore)
        return known

    # ------------------------------------------------------------------ references
    def _collect_refs(self) -> None:
        handled: set[int] = set()
        for automation in self.automations:
            handled.add(id(automation.raw))
            for key, value in automation.raw.items():
                role = {"triggers": "trigger", "trigger": "trigger", "conditions": "condition", "condition": "condition",
                        "actions": "action", "action": "action"}.get(key, "other")
                self._walk_value(value, key, automation.raw, automation.where, role, automation)
        for script in self.scripts:
            handled.add(id(script.raw))
            for key, value in script.raw.items():
                self._walk_value(value, key, script.raw, script.where, "action", None)
        config = self.config.config
        for section_list in self.sections.values():
            for section in section_list:
                if section.domain in ("automation", "script"):
                    continue
                if section.domain == "homeassistant":
                    self._walk_core(section)
                    continue
                owner = f'The "{section.key}" section' + (f' (package "{section.package}")' if section.package else "")
                self._walk_value(section.value, section.key, config, owner, "other", None, skip=handled)
        for board in self.config.dashboards:
            self._walk_value(board, None, None, "A dashboard", "dashboard", None)

    def _walk_core(self, section: Section) -> None:
        core = section.value
        if not isinstance(core, LMap):
            return
        customize = core.get("customize")
        if isinstance(customize, LMap):
            for key in customize:
                if isinstance(key, str) and "." in key:
                    self.refs.append(Ref(key, customize.file, customize.key_line(key), "customize",
                                         'The "customize" settings', "other"))

    def _walk_value(self, value: Any, key: Any, parent: Any, owner: str, role: str,
                    automation: Automation | None, skip: set[int] | None = None, branch: bool = False) -> None:
        if skip and id(value) in skip:
            return
        if isinstance(value, LMap):
            is_trigger_branch = branch or self._is_trigger_choice(value)
            if key in ENTITY_KEYS:
                for entity_key in value:
                    if isinstance(entity_key, str) and looks_like_known_entity(entity_key):
                        self._add_ref(entity_key, value.file, value.key_line(entity_key), "entity", owner, role)
            if "device_id" in value:
                for device in as_list(value["device_id"]):
                    if isinstance(device, str) and not is_template(device):
                        self.device_refs.append(DeviceRef(device, value.file, value.key_line("device_id"), owner))
            for child_key, child in value.items():
                if child_key == "device_id":
                    continue
                line = value.value_lines.get(child_key, value.line)
                if isinstance(child, str):
                    self._string(child, child_key, value, value.file, line, owner, role, automation, is_trigger_branch)
                elif isinstance(child, (LMap, LList)):
                    self._walk_value(child, child_key, value, owner, role, automation, skip, is_trigger_branch)
        elif isinstance(value, LList):
            for index, item in enumerate(value):
                line = value.item_line(index)
                if isinstance(item, str):
                    self._string(item, key, value, getattr(item, "file", "") or value.file, line, owner, role, automation, branch)
                elif isinstance(item, (LMap, LList)):
                    self._walk_value(item, key, value, owner, role, automation, skip, branch)
        elif isinstance(value, str):
            self._string(value, key, parent, getattr(value, "file", ""), getattr(value, "line", 0), owner, role, automation, branch)

    @staticmethod
    def _is_trigger_choice(mapping: LMap) -> bool:
        conditions = as_list(mapping.get("conditions")) + as_list(mapping.get("if"))
        return any(isinstance(c, LMap) and c.get("condition") == "trigger" for c in conditions)

    def _add_ref(self, entity_id: str, file: str, line: int, kind: str, owner: str, role: str, how: str = "") -> None:
        self.refs.append(Ref(entity_id, file, line, kind, owner, role, how))

    def _string(self, text: str, key: Any, parent: Any, file: str, line: int, owner: str, role: str,
                automation: Automation | None, branch: bool) -> None:
        if role == "dashboard":
            if is_template(text):
                for entity_id, how in analyse(text).entity_refs:
                    self._add_ref(entity_id, file, line, "dashboard", owner, role, how)
            elif looks_like_known_entity(text):
                self._add_ref(text, file, line, "dashboard", owner, role)
            return
        if is_template(text):
            start = line + 1 if isinstance(text, LStr) and text.style in ("|", ">") else line
            self.templates.append(TemplateUse(text, file, start, key, owner, role, automation, parent, branch))
            for entity_id, how in analyse(text).entity_refs:
                self._add_ref(entity_id, file, start, "template", owner, role, how)
            return
        if key in ENTITY_KEYS:
            for entity_id in entity_ids_in(text):
                if entity_id.lower() in ("all", "none"):
                    continue
                kind = "registry-id" if REGISTRY_ID_RE.match(entity_id) else "entity"
                self._add_ref(entity_id, file, line, kind, owner, role)
        elif key in ("action", "service", "service_template") and role != "trigger":
            name = text.strip()
            self.service_refs.append(ServiceRef(name, file, line, owner))
            if name.startswith("script.") and name not in SCRIPT_BUILTIN_SERVICES:
                self._add_ref(name, file, line, "script-call", owner, role)
        elif key == "scene" and looks_like_known_entity(text):
            self._add_ref(text, file, line, "scene", owner, role)
        elif key == "zone" and isinstance(text, str):
            self._add_ref(text, file, line, "zone", owner, role)
        elif key in NOT_ENTITY_KEYS:
            return
        elif looks_like_known_entity(text):
            self._add_ref(text, file, line, "string", owner, role)

    # ------------------------------------------------------------------ helpers for checks
    def iter_action_lists(self) -> Iterator[tuple[str, list, Automation | Script]]:
        for automation in self.automations:
            yield automation.where, automation.actions, automation
        for script in self.scripts:
            yield script.where, script.actions, script


def is_tag(value: Any, tag: str | None = None) -> bool:
    return isinstance(value, HATag) and (tag is None or value.tag == tag)
