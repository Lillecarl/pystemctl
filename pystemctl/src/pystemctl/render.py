"""Formatting helpers shared by the command handlers."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any

LOCAL_TIMEZONE = dt.datetime.now().astimezone().tzinfo


def usec_to_datetime(usec: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(usec / 1_000_000, tz=LOCAL_TIMEZONE)


def format_duration(delta: dt.timedelta) -> str:
    seconds = max(int(delta.total_seconds()), 0)
    days, seconds = divmod(seconds, 86_400)
    hours, seconds = divmod(seconds, 3_600)
    minutes, seconds = divmod(seconds, 60)

    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}min")
    if not parts:
        parts.append(f"{seconds}s")
    return " ".join(parts[:2])


def format_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    table = [list(map(str, headers)), *(list(map(str, row)) for row in rows)]
    widths = [max(len(row[i]) for row in table) for i in range(len(headers))]
    lines = [
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
        for row in table
    ]
    return "\n".join(lines)


def format_property_value(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, (list, tuple)):
        return " ".join(format_property_value(item) for item in value)
    return str(value)


def format_unit_status(name: str, props: Mapping[str, Any]) -> str:
    active = props.get("ActiveState", "unknown")
    sub = props.get("SubState", "")
    load = props.get("LoadState", "unknown")
    description = props.get("Description", "")
    fragment = props.get("FragmentPath", "")
    unit_file_state = props.get("UnitFileState", "")

    marker = {
        "active": "*",
        "activating": ">",
        "deactivating": "<",
        "failed": "x",
        "inactive": "-",
    }.get(active, "-")

    lines = [f"{marker} {name} - {description}" if description else f"{marker} {name}"]

    loaded_detail = fragment or "not-found"
    if unit_file_state:
        loaded_detail = f"{loaded_detail}; {unit_file_state}"
    lines.append(f"     Loaded: {load} ({loaded_detail})")

    active_line = f"     Active: {active} ({sub})" if sub else f"     Active: {active}"
    timestamp = props.get("ActiveEnterTimestamp")
    if isinstance(timestamp, int) and timestamp:
        when = usec_to_datetime(timestamp)
        age = format_duration(dt.datetime.now(tz=LOCAL_TIMEZONE) - when)
        active_line += f" since {when:%a %Y-%m-%d %H:%M:%S %Z}; {age} ago"
    lines.append(active_line)

    main_pid = props.get("MainPID")
    if isinstance(main_pid, int) and main_pid:
        lines.append(f"   Main PID: {main_pid}")

    result = props.get("Result")
    if result and result != "success":
        code = props.get("ExecMainCode")
        status = props.get("ExecMainStatus")
        lines.append(f"     Result: {result} (code={code}, status={status})")

    if props.get("Transient"):
        lines.append("  Transient: yes")

    cgroup = props.get("ControlGroup")
    if cgroup:
        lines.append(f"     CGroup: {cgroup}")

    return "\n".join(lines)
