"""Timestamp and priority parsing for the journal command line."""

from __future__ import annotations

import datetime as dt
import re

from ..errors import PystemctlError

PRIORITY_NAMES = ("emerg", "alert", "crit", "err", "warning", "notice", "info", "debug")

_RELATIVE_RE = re.compile(
    r"^(?P<sign>[-+]?)\s*(?P<count>\d+)\s*(?P<unit>s|sec|second|m|min|minute|h|hour|d|day|w|week)s?"
    r"(?:\s+ago)?$"
)
_UNIT_SECONDS = {
    "s": 1,
    "sec": 1,
    "second": 1,
    "m": 60,
    "min": 60,
    "minute": 60,
    "h": 3600,
    "hour": 3600,
    "d": 86400,
    "day": 86400,
    "w": 604800,
    "week": 604800,
}


def parse_timestamp(value: str, *, now: dt.datetime | None = None) -> dt.datetime:
    """Parse the forms journalctl accepts: ISO, ``@epoch``, and relative."""
    text = value.strip()
    local = dt.datetime.now().astimezone().tzinfo
    reference = now or dt.datetime.now(tz=local)

    if text.startswith("@"):
        return dt.datetime.fromtimestamp(float(text[1:]), tz=local)

    lowered = text.lower()
    if lowered == "now":
        return reference
    if lowered in {"today", "yesterday", "tomorrow"}:
        midnight = reference.replace(hour=0, minute=0, second=0, microsecond=0)
        offset = {"today": 0, "yesterday": -1, "tomorrow": 1}[lowered]
        return midnight + dt.timedelta(days=offset)

    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        parsed = None
    if parsed is not None:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=local)
        return parsed

    match = _RELATIVE_RE.match(text)
    if match:
        count = int(match.group("count"))
        direction = 1 if match.group("sign") == "+" else -1
        return reference + dt.timedelta(
            seconds=direction * count * _UNIT_SECONDS[match.group("unit")]
        )

    raise PystemctlError(f"could not parse timestamp: {value!r}")


def priority_value(value: str) -> int:
    lowered = value.strip().lower()
    if lowered in PRIORITY_NAMES:
        return PRIORITY_NAMES.index(lowered)
    try:
        number = int(lowered)
    except ValueError as error:
        raise PystemctlError(f"unknown priority: {value!r}") from error
    if not 0 <= number <= 7:
        raise PystemctlError(f"priority out of range: {value!r}")
    return number
