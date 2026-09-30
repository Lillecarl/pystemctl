"""Small helpers shared by the command handlers."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections.abc import Sequence
from typing import Any

from ..errors import PystemctlError
from ..systemd import Unit


def emit(args: argparse.Namespace, text: str | None, payload: Any) -> None:
    if getattr(args, "json", False):
        print(json.dumps(payload, default=str, ensure_ascii=False))
    elif text is not None:
        print(text)


def strip_separator(command: Sequence[str]) -> list[str]:
    command = list(command)
    if command and command[0] == "--":
        command = command[1:]
    return command


def parse_property(text: str) -> tuple[str, tuple[str, Any]]:
    name, separator, value = text.partition("=")
    if not separator:
        raise PystemctlError(f"property must be NAME=VALUE: {text!r}")
    typename = "s"
    if ":" in name:
        name, _, typename = name.partition(":")
    if typename == "b":
        typed: Any = value.lower() in {"1", "true", "yes", "on"}
    elif typename in {"i", "u", "t"}:
        typed = int(value)
    elif typename == "as":
        typed = [part for part in value.split(",") if part]
    elif typename == "s":
        typed = value
    else:
        raise PystemctlError(f"unsupported property type: {typename!r}")
    return name, (typename, typed)


def parse_environment(items: Sequence[str]) -> dict[str, str]:
    environment: dict[str, str] = {}
    for item in items:
        key, separator, value = item.partition("=")
        if not separator:
            raise PystemctlError(f"environment must be KEY=VALUE: {item!r}")
        environment[key] = value
    return environment


def tail_count(lines: int | None, follow: bool, since: dt.datetime | None) -> int | None:
    if lines is not None:
        return lines
    if since is not None and not follow:
        return None
    return 10


def unit_payload(unit: Unit) -> dict[str, Any]:
    return {
        "unit": unit.name,
        "description": unit.description,
        "load": unit.load_state,
        "active": unit.active_state,
        "sub": unit.sub_state,
        "path": unit.path,
    }


def unit_payload_from_props(name: str, props: dict[str, Any]) -> dict[str, Any]:
    return {
        "unit": name,
        "description": props.get("Description"),
        "load": props.get("LoadState"),
        "active": props.get("ActiveState"),
        "sub": props.get("SubState"),
        "path": props.get("FragmentPath"),
        "transient": bool(props.get("Transient")),
        "result": props.get("Result"),
        "main_pid": props.get("MainPID"),
    }


def jsonable(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value
