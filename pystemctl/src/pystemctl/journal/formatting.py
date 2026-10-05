"""Rendering journal entries in journalctl's output modes."""

from __future__ import annotations

import base64
import datetime as dt
import json
import uuid
from collections.abc import Sequence
from typing import Any

from .reader import entries, open_reader

OUTPUT_MODES = (
    "short",
    "short-iso",
    "short-precise",
    "short-full",
    "cat",
    "json",
    "json-pretty",
    "verbose",
)


async def print_entries(
    *,
    system_units: Sequence[str] = (),
    user_units: Sequence[str] = (),
    tail: int | None = None,
    follow: bool = False,
    since: dt.datetime | None = None,
    until: dt.datetime | None = None,
    priority: int | None = None,
    boot: str | bool | None = None,
    mode: str = "short",
    skip_notices: bool = False,
) -> None:
    reader = open_reader(
        system_units=system_units, user_units=user_units, priority=priority, boot=boot
    )
    async for entry in entries(
        reader, since=since, until=until, tail=tail, follow=follow,
        skip_notices=skip_notices,
    ):
        print(format_entry(entry, mode), flush=True)


def format_entry(entry: dict[str, Any], mode: str) -> str:
    if mode in {"json", "json-pretty"}:
        data = {key: _jsonify(value) for key, value in entry.items()}
        return json.dumps(data, indent=2 if mode == "json-pretty" else None, ensure_ascii=False)
    if mode == "verbose":
        return "\n".join(f"{key}={_scalar(entry[key])}" for key in sorted(entry))
    if mode == "cat":
        return _message(entry)

    timestamp = entry.get("__REALTIME_TIMESTAMP")
    if not isinstance(timestamp, dt.datetime):
        timestamp = dt.datetime.now().astimezone()
    if mode == "short-iso":
        stamp = timestamp.strftime("%Y-%m-%dT%H:%M:%S%z")
    elif mode == "short-precise":
        stamp = timestamp.strftime("%b %d %H:%M:%S.%f")
    elif mode == "short-full":
        stamp = timestamp.strftime("%a %Y-%m-%d %H:%M:%S %Z")
    else:
        stamp = timestamp.strftime("%b %d %H:%M:%S")

    host = entry.get("_HOSTNAME", "")
    identifier = _identifier(entry)
    pid = entry.get("_PID") or entry.get("SYSLOG_PID")
    prefix = f"{stamp} {host} {identifier}".rstrip()
    if pid:
        prefix += f"[{pid}]"
    return f"{prefix}: {_message(entry)}"


def entry_message(entry: dict[str, Any]) -> str:
    """The entry's MESSAGE as text, for matching against a pattern."""
    return _message(entry)


def _message(entry: dict[str, Any]) -> str:
    message = entry.get("MESSAGE")
    if isinstance(message, bytes):
        return message.decode("utf-8", "replace")
    return "" if message is None else str(message)


def _identifier(entry: dict[str, Any]) -> str:
    for key in ("SYSLOG_IDENTIFIER", "_COMM", "_SYSTEMD_USER_UNIT", "_SYSTEMD_UNIT", "_EXE"):
        value = entry.get(key)
        if value:
            return str(value)
    return "unknown"


def _jsonify(value: Any) -> Any:
    if isinstance(value, dt.datetime):
        return int(value.timestamp() * 1_000_000)
    if isinstance(value, dt.timedelta):
        return int(value.total_seconds() * 1_000_000)
    if isinstance(value, uuid.UUID):
        return value.hex
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if isinstance(value, (list, tuple)):
        return [_jsonify(item) for item in value]
    return value


def _scalar(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, (list, tuple)):
        return " ".join(str(item) for item in value)
    return str(value)
