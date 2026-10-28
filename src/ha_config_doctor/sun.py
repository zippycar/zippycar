"""Work out the earliest and latest sunrise and sunset through the year.

Uses the well-known NOAA approximation (accurate to a minute or two, which is
plenty here). If the home location isn't known we fall back to wide ranges
that cover most places people live, and the wording of findings says "may".
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

# Used when the location is unknown: wide enough to cover latitudes up to about 60°.
DEFAULT_RANGES = {"sunrise": (3 * 3600 + 30 * 60, 9 * 3600 + 30 * 60), "sunset": (15 * 3600 + 30 * 60, 22 * 3600 + 30 * 60)}


def _sun_utc_minutes(day: date, latitude: float, longitude: float) -> tuple[float, float] | None:
    gamma = 2 * math.pi / 365 * (day.timetuple().tm_yday - 1)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
                       - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))
    decl = (0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma) - 0.006758 * math.cos(2 * gamma)
            + 0.000907 * math.sin(2 * gamma) - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma))
    lat = math.radians(latitude)
    value = math.cos(math.radians(90.833)) / (math.cos(lat) * math.cos(decl)) - math.tan(lat) * math.tan(decl)
    if value < -1 or value > 1:
        return None  # midnight sun or polar night
    hour_angle = math.degrees(math.acos(value))
    sunrise = 720 - 4 * (longitude + hour_angle) - eqtime
    sunset = 720 - 4 * (longitude - hour_angle) - eqtime
    return sunrise, sunset


def _offset_seconds(day: date, tz_name: str | None, longitude: float) -> float:
    if tz_name:
        try:
            from zoneinfo import ZoneInfo

            zone = ZoneInfo(tz_name)
            noon = datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc)
            offset = noon.astimezone(zone).utcoffset()
            if offset is not None:
                return offset.total_seconds()
        except Exception:
            pass
    return round(longitude / 15) * 3600  # rough guess from longitude


def yearly_ranges(location: tuple[float, float, str | None] | None, year: int = 2026) -> dict[str, tuple[int, int]]:
    """{"sunrise": (earliest, latest), "sunset": (earliest, latest)} in seconds after local midnight."""

    if location is None:
        return dict(DEFAULT_RANGES)
    latitude, longitude, tz_name = location
    rises: list[float] = []
    sets: list[float] = []
    day = date(year, 1, 1)
    while day.year == year:
        times = _sun_utc_minutes(day, latitude, longitude)
        if times is not None:
            offset = _offset_seconds(day, tz_name, longitude)
            rises.append((times[0] * 60 + offset) % 86400)
            sets.append((times[1] * 60 + offset) % 86400)
        day += timedelta(days=3)
    if not rises:
        return dict(DEFAULT_RANGES)
    return {"sunrise": (int(min(rises)), int(max(rises))), "sunset": (int(min(sets)), int(max(sets)))}
