"""Small helpers shared by several modules."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable

ENTITY_ID_RE = re.compile(r"^(?!.+__)(?!_)[\da-z_]+(?<!_)\.(?!_)[\da-z_]+(?<!_)$")
REGISTRY_ID_RE = re.compile(r"^[0-9a-f]{32}$")
TIME_RE = re.compile(r"^(\d{1,2}):(\d{1,2})(?::(\d{1,2})(?:\.\d+)?)?$")

# Domains (the part before the dot) that Home Assistant entities can have.
KNOWN_DOMAINS = frozenset(
    """
    ai_task air_quality alarm_control_panel alert assist_satellite automation binary_sensor button
    calendar camera climate conversation counter cover date datetime device_tracker event fan
    geo_location group humidifier image image_processing input_boolean input_button input_datetime
    input_number input_select input_text lawn_mower light lock media_player notify number person
    plant proximity remote scene schedule script select sensor siren stt sun switch tag text time
    timer todo tts update vacuum valve wake_word water_heater weather zone
    """.split()
)

HELPER_DOMAINS = (
    "input_boolean", "input_number", "input_select", "input_text", "input_datetime",
    "input_button", "counter", "timer", "schedule",
)

# Domains whose state is never a number, so a numeric_state trigger on them can't work.
NON_NUMERIC_DOMAINS = frozenset(
    """
    binary_sensor input_boolean switch light lock cover fan automation script scene person
    device_tracker media_player alarm_control_panel vacuum input_select select input_text
    input_button button calendar update siren remote sun zone group event tag todo climate
    water_heater humidifier weather lawn_mower valve
    """.split()
)


def is_entity_id(value: Any) -> bool:
    return isinstance(value, str) and bool(ENTITY_ID_RE.match(value))


def looks_like_known_entity(value: Any) -> bool:
    return is_entity_id(value) and value.split(".", 1)[0] in KNOWN_DOMAINS


def slugify(text: Any) -> str:
    """Approximate Home Assistant's ``slugify`` (used to turn names into entity ids)."""

    value = unicodedata.normalize("NFKD", str(text))
    value = value.encode("ascii", "ignore").decode("ascii").lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = value.strip("_")
    return value or "unknown"


def as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    return [value]


def entity_ids_in(value: Any) -> list[str]:
    """Entity ids given to an ``entity_id:`` setting (a list, or text separated by commas)."""

    out: list[str] = []
    for item in as_list(value):
        if isinstance(item, str):
            for part in item.split(","):
                part = part.strip()
                if part:
                    out.append(part)
    return out


def is_template(value: Any) -> bool:
    return isinstance(value, str) and ("{{" in value or "{%" in value)


def parse_clock(value: Any) -> int | None:
    """Seconds after midnight for "HH:MM" or "HH:MM:SS" text, or None if it isn't valid."""

    if not isinstance(value, str):
        return None
    match = TIME_RE.match(value.strip())
    if not match:
        return None
    hours, minutes, seconds = int(match.group(1)), int(match.group(2)), int(match.group(3) or 0)
    if hours > 23 or minutes > 59 or seconds > 59:
        return None
    return hours * 3600 + minutes * 60 + seconds


def clock_text(seconds: float) -> str:
    seconds = int(round(seconds)) % 86400
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}"


def duration_seconds(value: Any) -> float | None:
    """How long a delay / for / timeout lasts, in seconds; None if unknown (e.g. a template)."""

    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if is_template(text):
            return None
        try:
            return float(text)
        except ValueError:
            pass
        negative = text.startswith("-")
        parts = text.lstrip("-").split(":")
        if 2 <= len(parts) <= 3:
            try:
                nums = [float(p) for p in parts]
            except ValueError:
                return None
            if len(nums) == 2:
                total = nums[0] * 3600 + nums[1] * 60
            else:
                total = nums[0] * 3600 + nums[1] * 60 + nums[2]
            return -total if negative else total
        return None
    if isinstance(value, dict):
        total = 0.0
        units = {"days": 86400, "hours": 3600, "minutes": 60, "seconds": 1, "milliseconds": 0.001}
        for key, item in value.items():
            if key not in units:
                return None
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                if isinstance(item, str):
                    try:
                        item = float(item)
                    except ValueError:
                        return None
                else:
                    return None
            total += float(item) * units[key]
        return total
    return None


def human_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} second{'s' if seconds != 1 else ''}"
    if seconds < 3600:
        minutes, rest = divmod(seconds, 60)
        text = f"{minutes} minute{'s' if minutes != 1 else ''}"
        if rest:
            text += f" {rest} second{'s' if rest != 1 else ''}"
        return text
    hours = seconds / 3600
    if hours == int(hours):
        return f"{int(hours)} hour{'s' if hours != 1 else ''}"
    return f"{hours:.1f} hours"


def quote_list(items: Iterable[str], limit: int = 6) -> str:
    items = [str(i) for i in items]
    shown = ", ".join(f'"{i}"' for i in items[:limit])
    if len(items) > limit:
        shown += f" and {len(items) - limit} more"
    return shown
