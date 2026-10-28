"""Read YAML exactly the way Home Assistant does, but remember where everything is.

Home Assistant uses PyYAML's "safe" loader, which follows the older YAML 1.1
rules. That matters: under those rules an unquoted ``on`` becomes the boolean
``True`` and an unquoted ``7:30`` becomes the number 450. We use the very same
rules so that what we report matches what Home Assistant really sees.

Every mapping, list and piece of text we build records the file and line it
came from, so findings can point at the right line. Home Assistant's special
``!tags`` are kept as :class:`HATag` objects; resolving ``!include`` is done
later by :mod:`ha_config_doctor.configtree`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

INCLUDE_TAGS = (
    "!include",
    "!include_dir_list",
    "!include_dir_named",
    "!include_dir_merge_list",
    "!include_dir_merge_named",
)
HA_TAGS = INCLUDE_TAGS + ("!secret", "!input", "!env_var")


@dataclass(frozen=True)
class Raw:
    """The text of a scalar exactly as typed, before YAML turned it into a value."""

    text: str
    style: str | None  # None = plain (no quotes), "'" or '"' = quoted, "|" or ">" = block
    tag: str


class LMap(dict):
    """A dict that remembers the file and line of itself and of each key."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.file = ""
        self.line = 0
        self.key_lines: dict[Any, int] = {}
        self.value_lines: dict[Any, int] = {}
        self.raw: dict[Any, Raw] = {}

    def key_line(self, key: Any) -> int:
        return self.key_lines.get(key, self.line)

    def raw_of(self, key: Any) -> Raw | None:
        return self.raw.get(key)


class LList(list):
    """A list that remembers the file and line of itself and of each item."""

    def __init__(self, *args: Any) -> None:
        super().__init__(*args)
        self.file = ""
        self.line = 0
        self.item_lines: list[int] = []
        self.raw_items: list[Raw | None] = []

    def item_line(self, index: int) -> int:
        if 0 <= index < len(self.item_lines):
            return self.item_lines[index]
        return self.line


class LStr(str):
    """A piece of text that remembers the file and line it came from."""

    file: str
    line: int
    style: str | None

    def __new__(cls, value: str, file: str = "", line: int = 0, style: str | None = None) -> "LStr":
        obj = super().__new__(cls, value)
        obj.file = file
        obj.line = line
        obj.style = style
        return obj


@dataclass(eq=True)
class HATag:
    """One of Home Assistant's special ``!tags`` such as ``!include`` or ``!secret``."""

    tag: str
    value: Any
    file: str = field(default="", compare=False)
    line: int = field(default=0, compare=False)

    def __hash__(self) -> int:
        return hash((self.tag, str(self.value)))

    @property
    def text(self) -> str:
        return self.value if isinstance(self.value, str) else ""


@dataclass
class YamlProblem:
    line: int
    message: str  # plain English
    technical: str  # PyYAML's own short wording (never contains file contents)


@dataclass
class ParsedYaml:
    data: Any
    problem: YamlProblem | None = None
    duplicates: list[tuple[Any, int, int]] = field(default_factory=list)  # (key, first line, second line)
    tags: list[HATag] = field(default_factory=list)


def _line(node: yaml.Node) -> int:
    return node.start_mark.line + 1


class _HALoader(yaml.SafeLoader):
    """PyYAML's safe loader (the same rules Home Assistant uses) with line tracking."""

    def __init__(self, stream: str, filename: str) -> None:
        super().__init__(stream)
        self.filename = filename
        self.duplicates: list[tuple[Any, int, int]] = []
        self.found_tags: list[HATag] = []


def _key(loader: _HALoader, node: yaml.Node) -> Any:
    key = loader.construct_object(node, deep=True)
    try:
        hash(key)
    except TypeError:
        key = str(key)
    return key


def _put(loader: _HALoader, mapping: LMap, key: Any, key_node: yaml.Node, value_node: yaml.Node) -> None:
    mapping[key] = loader.construct_object(value_node, deep=True)
    mapping.key_lines[key] = _line(key_node)
    mapping.value_lines[key] = _line(value_node)
    if isinstance(value_node, yaml.ScalarNode):
        mapping.raw[key] = Raw(value_node.value, value_node.style, value_node.tag)
    else:
        mapping.raw.pop(key, None)


def _construct_map(loader: _HALoader, node: yaml.MappingNode) -> LMap:
    result = LMap()
    result.file = loader.filename
    result.line = _line(node)
    own: list[tuple[yaml.Node, yaml.Node]] = []
    merge_sources: list[LMap] = []
    for key_node, value_node in node.value:
        if key_node.tag == "tag:yaml.org,2002:merge":
            targets = value_node.value if isinstance(value_node, yaml.SequenceNode) else [value_node]
            for target in targets:
                merged = loader.construct_object(target, deep=True)
                if isinstance(merged, LMap):
                    merge_sources.append(merged)
        else:
            own.append((key_node, value_node))
    # Values pulled in with "<<: *anchor" act as defaults; the earliest source wins.
    for source in merge_sources:
        for key, value in source.items():
            if key not in result:
                result[key] = value
                result.key_lines[key] = source.key_lines.get(key, source.line)
                result.value_lines[key] = source.value_lines.get(key, source.line)
                if key in source.raw:
                    result.raw[key] = source.raw[key]
    seen: dict[Any, int] = {}
    for key_node, value_node in own:
        key = _key(loader, key_node)
        if key in seen:
            loader.duplicates.append((key, seen[key], _line(key_node)))
        seen[key] = _line(key_node)
        _put(loader, result, key, key_node, value_node)  # like Home Assistant, the last one wins
    return result


def _construct_seq(loader: _HALoader, node: yaml.SequenceNode) -> LList:
    result = LList()
    result.file = loader.filename
    result.line = _line(node)
    for child in node.value:
        result.append(loader.construct_object(child, deep=True))
        result.item_lines.append(_line(child))
        result.raw_items.append(Raw(child.value, child.style, child.tag) if isinstance(child, yaml.ScalarNode) else None)
    return result


def _construct_str(loader: _HALoader, node: yaml.ScalarNode) -> LStr:
    return LStr(loader.construct_scalar(node), loader.filename, _line(node), node.style)


def _construct_tag(loader: _HALoader, node: yaml.Node) -> HATag:
    if isinstance(node, yaml.ScalarNode):
        value: Any = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = _construct_seq(loader, node)
    else:
        value = _construct_map(loader, node)
    tag = HATag(node.tag, value, loader.filename, _line(node))
    loader.found_tags.append(tag)
    return tag


_HALoader.add_constructor("tag:yaml.org,2002:map", _construct_map)
_HALoader.add_constructor("tag:yaml.org,2002:seq", _construct_seq)
_HALoader.add_constructor("tag:yaml.org,2002:str", _construct_str)
for _tag in HA_TAGS:
    _HALoader.add_constructor(_tag, _construct_tag)
_HALoader.add_constructor(None, _construct_tag)  # unknown tags are reported by the checks


_PLAIN_REASONS = (
    ("found character '\\t'", "There is a TAB character here. YAML only allows spaces for indenting, never TABs."),
    ("mapping values are not allowed", "A colon (:) is in a place YAML doesn't expect. Often a value containing a colon needs quotes around it, or the line is indented wrongly."),
    ("could not find expected ':'", "A line seems to be missing its colon (:), or a quote mark was opened and never closed."),
    ("found undefined alias", "This uses *name to repeat a block, but no block called &name was defined."),
    ("expected <block end>", "The indentation (spaces at the start of the line) doesn't line up with the lines around it."),
    ("did not find expected key", "The indentation (spaces at the start of the line) doesn't line up with the lines around it."),
    ("did not find expected '-' indicator", "A list item (a line starting with -) is indented differently from the others."),
    ("found unexpected end of stream", "The file ends in the middle of something — usually a quote mark that was never closed."),
    ("found duplicate anchor", "The same &name is defined twice."),
    ("expected a single document", "The file contains more than one YAML document (separated by ---). Home Assistant only reads one."),
    ("found unknown escape character", "Inside double quotes, a backslash (\\) starts a special code. Use single quotes, or write \\\\ for a real backslash."),
    ("while scanning a quoted scalar", "A quote mark was opened and never closed."),
    ("found unconstructable recursive node", "A block refers back to itself, which YAML can't handle."),
)


def _plain_reason(technical: str) -> str:
    for needle, plain in _PLAIN_REASONS:
        if needle in technical:
            return plain
    return "The layout of the file doesn't follow YAML's rules at this point."


def parse_yaml(text: str, filename: str) -> ParsedYaml:
    """Parse one YAML document. Never raises for bad input; problems are returned."""

    loader = _HALoader(text, filename)
    try:
        data = loader.get_single_data()
    except yaml.MarkedYAMLError as err:
        mark = err.problem_mark or err.context_mark
        technical = " ".join(part for part in (err.context, err.problem) if part)
        return ParsedYaml(
            None,
            YamlProblem(mark.line + 1 if mark else 1, _plain_reason(technical), technical),
            loader.duplicates,
            loader.found_tags,
        )
    except yaml.YAMLError as err:  # pragma: no cover - PyYAML almost always gives a mark
        technical = type(err).__name__
        return ParsedYaml(None, YamlProblem(1, _plain_reason(technical), technical))
    except RecursionError:
        return ParsedYaml(None, YamlProblem(1, "The file is nested too deeply to read.", "RecursionError"))
    finally:
        loader.dispose()
    return ParsedYaml(data, None, loader.duplicates, loader.found_tags)


class NotUtf8(Exception):
    pass


def read_text(path: Path) -> str:
    """Read a text file as UTF-8 (ignoring a Windows 'byte order mark')."""

    raw = path.read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as err:
        raise NotUtf8(str(path)) from err


def to_plain(value: Any) -> Any:
    """Turn our located objects back into plain Python values (used for comparisons)."""

    if isinstance(value, dict):
        return {to_plain(k): to_plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_plain(v) for v in value]
    if isinstance(value, HATag):
        return ("tag", value.tag, to_plain(value.value))
    if isinstance(value, LStr):
        return str(value)
    return value


def line_of(container: Any, key: Any = None, default: int = 0) -> int:
    """The line of a key in a mapping, an item in a list, or the container itself."""

    if isinstance(container, LMap):
        return container.key_line(key) if key is not None else container.line
    if isinstance(container, LList):
        return container.item_line(key) if isinstance(key, int) else container.line
    if isinstance(container, (LStr, HATag)):
        return container.line
    return default


def file_of(value: Any, default: str = "") -> str:
    return getattr(value, "file", "") or default
