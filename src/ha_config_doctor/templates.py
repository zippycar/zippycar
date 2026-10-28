"""Look inside Home Assistant templates (the code between {{ }} and {% %}).

We use Jinja's own parser — the same template language Home Assistant uses —
so we can find typing mistakes and look at what each template really does,
instead of guessing with text searches.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from jinja2 import nodes
from jinja2.exceptions import TemplateSyntaxError
from jinja2.sandbox import ImmutableSandboxedEnvironment

from .util import KNOWN_DOMAINS, looks_like_known_entity

_ENV = ImmutableSandboxedEnvironment(extensions=["jinja2.ext.loopcontrols", "jinja2.ext.do"])

# Where the "default" argument goes for filters and functions that fail without one.
# Filters: index into the filter's own arguments. Functions: index into the call arguments.
_FILTER_DEFAULT_INDEX = {
    "float": 0, "int": 0, "round": 2, "as_timestamp": 0, "as_datetime": 0, "timestamp_custom": 2,
    "timestamp_local": 0, "timestamp_utc": 0, "strptime": 1, "multiply": 1, "log": 1, "bool": 0,
}
_FUNCTION_DEFAULT_INDEX = {
    "float": 1, "int": 1, "as_timestamp": 1, "as_datetime": 1, "strptime": 2, "log": 2, "bool": 1,
}
# These always need a default (any input can be non-numeric); the rest only when fed straight from a state.
_ALWAYS_NEED_DEFAULT = {"float", "int"}

_ENTITY_FUNCTIONS = {
    "states", "is_state", "state_attr", "is_state_attr", "has_value", "expand", "closest",
    "device_id", "area_name", "area_id", "state_translated", "is_hidden_entity",
}
_STATE_ATTRS = {"state", "attributes", "last_changed", "last_updated", "last_reported", "name", "object_id", "domain", "context"}
TRIGGER_STATE_ONLY_ATTRS = {"to_state", "from_state", "entity_id"}


@dataclass
class TemplateInfo:
    syntax_error: tuple[int, str] | None = None
    entity_refs: list[tuple[str, str]] = field(default_factory=list)  # (entity id, how it is used)
    no_default: list[str] = field(default_factory=list)
    text_number_compare: list[str] = field(default_factory=list)
    direct_state: list[str] = field(default_factory=list)
    trigger_attrs: set[str] = field(default_factory=set)
    trigger_guarded: bool = False
    forecast_attribute: bool = False
    uses_now: bool = False


def _call_name(node: nodes.Node) -> str | None:
    if isinstance(node, nodes.Call) and isinstance(node.node, nodes.Name):
        return node.node.name
    return None


def _has_default(args: list, kwargs: list, index: int) -> bool:
    return len(args) > index or any(kw.key == "default" for kw in kwargs)


def _states_chain(node: nodes.Node) -> str | None:
    """'sensor.x' for the template code states.sensor.x, otherwise None."""

    if (
        isinstance(node, nodes.Getattr)
        and isinstance(node.node, nodes.Getattr)
        and isinstance(node.node.node, nodes.Name)
        and node.node.node.name == "states"
        and node.node.attr in KNOWN_DOMAINS
    ):
        return f"{node.node.attr}.{node.attr}"
    return None


def _states_item(node: nodes.Node) -> str | None:
    """'sensor.x' for states['sensor.x']."""

    if (
        isinstance(node, nodes.Getitem)
        and isinstance(node.node, nodes.Name)
        and node.node.name == "states"
        and isinstance(node.arg, nodes.Const)
        and isinstance(node.arg.value, str)
    ):
        return node.arg.value
    return None


def _is_state_text(node: nodes.Node) -> bool:
    """True when the expression is a state, which is always text."""

    if _call_name(node) == "states":
        return True
    if isinstance(node, nodes.Getattr) and node.attr == "state":
        base = node.node
        if _states_chain(base) or _states_item(base):
            return True
        if isinstance(base, nodes.Getattr) and isinstance(base.node, nodes.Name) and base.node.name == "trigger":
            return True
    return False


_SAFE_NAMES = {"now", "utcnow", "repeat", "loop", "range", "true", "false", "none", "True", "False", "None"}


def _unsafe_source(node: nodes.Node) -> bool:
    """True when the value may come from an entity's state, so it may be 'unavailable' or 'unknown'."""

    if isinstance(node, nodes.Call):
        return _call_name(node) in ("states", "state_attr")
    if isinstance(node, nodes.Name):
        return node.name not in _SAFE_NAMES  # a variable might hold a state
    if isinstance(node, (nodes.Getattr, nodes.Getitem)):
        base = node.node
        while isinstance(base, (nodes.Getattr, nodes.Getitem)):
            base = base.node
        if isinstance(base, nodes.Call):
            return False  # e.g. now().hour
        return isinstance(base, nodes.Name) and base.name not in _SAFE_NAMES
    if isinstance(node, nodes.Filter):
        if node.name in _ALWAYS_NEED_DEFAULT:
            return False  # reported on its own already, or safe because it has a default
        return _unsafe_source(node.node) if node.node is not None else False
    if isinstance(node, (nodes.BinExpr, nodes.Compare, nodes.CondExpr)):
        return any(_unsafe_source(child) for child in node.iter_child_nodes())
    return False


def _is_number(node: nodes.Node) -> bool:
    return isinstance(node, nodes.Const) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool)


def _walk(node: nodes.Node, parent: nodes.Node | None, info: TemplateInfo) -> None:
    if isinstance(node, nodes.Filter):
        index = _FILTER_DEFAULT_INDEX.get(node.name)
        if index is not None and not node.dyn_args and not node.dyn_kwargs and not _has_default(node.args, node.kwargs, index):
            source = node.node
            if source is not None and _unsafe_source(source):
                info.no_default.append(f"| {node.name}")
    elif isinstance(node, nodes.Call):
        name = _call_name(node)
        if name in _FUNCTION_DEFAULT_INDEX and not node.dyn_args and not node.dyn_kwargs:
            if not _has_default(node.args, node.kwargs, _FUNCTION_DEFAULT_INDEX[name]) and node.args:
                first = node.args[0]
                if _unsafe_source(first):
                    info.no_default.append(f"{name}()")
        if name in ("now", "utcnow"):
            info.uses_now = True
        if name in _ENTITY_FUNCTIONS and node.args:
            first = node.args[0]
            values = []
            if isinstance(first, nodes.Const) and isinstance(first.value, str):
                values = [first.value]
            elif isinstance(first, nodes.List):
                values = [item.value for item in first.items if isinstance(item, nodes.Const) and isinstance(item.value, str)]
            for value in values:
                info.entity_refs.append((value, name))
            if name == "state_attr" and len(node.args) > 1:
                second = node.args[1]
                if isinstance(second, nodes.Const) and second.value == "forecast":
                    info.forecast_attribute = True
    elif isinstance(node, nodes.Getattr):
        entity = _states_chain(node)
        if entity:
            info.entity_refs.append((entity, "states."))
            if isinstance(parent, nodes.Getattr) and parent.attr in _STATE_ATTRS:
                info.direct_state.append(entity)
        if isinstance(node.node, nodes.Name) and node.node.name == "trigger":
            if node.attr in ("platform", "id", "idx"):
                info.trigger_guarded = True
            else:
                info.trigger_attrs.add(node.attr)
        if node.attr == "forecast" and isinstance(node.node, nodes.Getattr) and node.node.attr == "attributes":
            info.forecast_attribute = True
    elif isinstance(node, nodes.Getitem):
        entity = _states_item(node)
        if entity:
            info.entity_refs.append((entity, "states[]"))
            if isinstance(parent, nodes.Getattr) and parent.attr in _STATE_ATTRS:
                info.direct_state.append(entity)
    elif isinstance(node, nodes.Compare):
        sides = [node.expr] + [operand.expr for operand in node.ops]
        for index, operand in enumerate(node.ops):
            left, right = sides[index], sides[index + 1]
            if operand.op in ("gt", "gteq", "lt", "lteq", "eq", "ne"):
                if (_is_state_text(left) and _is_number(right)) or (_is_number(left) and _is_state_text(right)):
                    info.text_number_compare.append(operand.op)
    elif isinstance(node, nodes.Test):
        if node.name in ("defined", "undefined", "none"):
            info.trigger_guarded = True
    elif isinstance(node, nodes.Const) and isinstance(node.value, str):
        if looks_like_known_entity(node.value) and not isinstance(parent, nodes.Call):
            info.entity_refs.append((node.value, "text"))
    for child in node.iter_child_nodes():
        _walk(child, node, info)


@lru_cache(maxsize=4096)
def analyse(text: str) -> TemplateInfo:
    info = TemplateInfo()
    try:
        tree = _ENV.parse(text)
    except TemplateSyntaxError as err:
        info.syntax_error = (err.lineno or 1, err.message or "syntax error")
        return info
    except Exception as err:  # pragma: no cover - Jinja is very robust
        info.syntax_error = (1, type(err).__name__)
        return info
    _walk(tree, None, info)
    return info
