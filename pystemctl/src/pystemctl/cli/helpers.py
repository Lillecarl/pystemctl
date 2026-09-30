"""Small helpers shared by the command handlers."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections.abc import Sequence
from typing import Any

from .. import systemd as sd
from ..bus import Bus
from ..errors import PystemctlError
from ..systemd import Unit


async def resolve_target(bus: Bus, args: argparse.Namespace) -> str:
    """Return the unit the command should act on.

    A unit name is used as given. Tags select the newest matching job; when
    several matched, the others are named on stderr so a surprising choice is
    visible rather than silent.
    """
    tags = getattr(args, "tags", None)
    if not tags and getattr(args, "unit", None):
        return sd.normalize_unit_name(args.unit)

    chosen, others = await sd.resolve(bus, tags=tags or ())
    if chosen is None:
        raise PystemctlError("no unit or tag given")
    if others:
        print(
            f"pystemctl: {len(others) + 1} jobs match {', '.join(tags)}; "
            f"using the newest, {chosen.name} "
            f"(also: {', '.join(job.name for job in others)})",
            file=sys.stderr,
        )
    return chosen.name


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
