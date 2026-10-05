"""Small helpers shared by the command handlers."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import anyio

from .. import journal as jr
from .. import systemd as sd
from ..bus import Bus, Scope
from ..errors import PystemctlError
from ..systemd import Unit


async def _collected_fallback(
    args: argparse.Namespace, tags: Sequence[str], missing: PystemctlError
) -> str:
    """Name of a finished job from its journal entries, or re-raise.

    The manager unloads a finished transient unit, so the bus cannot resolve
    its tag anymore; the unit's own log lines outlive it and carry the tags.
    A job that logged nothing leaves no trace, and then the original miss
    stands: silence from the journal is not a unit.
    """
    name = None
    try:
        system = getattr(args, "scope", Scope.USER) is Scope.SYSTEM
        name = await jr.newest_unit_for_tags(tags, system=system)
    except PystemctlError:
        name = None
    if name is None:
        raise missing
    print(
        f"pystemctl: {name} already finished and was collected; reading its journal",
        file=sys.stderr,
    )
    return name


async def resolve_target(bus: Bus, args: argparse.Namespace) -> str:
    """Return the unit the command should act on.

    A unit name is used as given. Tags select the newest matching job; when
    several matched, the others are named on stderr so a surprising choice is
    visible rather than silent.
    """
    tags = getattr(args, "tags", None)
    if not tags and getattr(args, "unit", None):
        return sd.normalize_unit_name(args.unit)

    try:
        chosen, others = await sd.resolve(bus, tags=tags or ())
    except PystemctlError as missing:
        if not tags:
            raise
        return await _collected_fallback(args, tags, missing)
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


async def resolve_units(bus: Bus, args: argparse.Namespace) -> list[str]:
    """Unit names from the positionals plus the newest job matching --tag.

    ``logs`` and ``status`` read any number of units, so tags resolve to one
    more name on the list rather than replacing it. Several matches name the
    others on stderr, the way resolve_target already does.
    """
    units = [sd.normalize_unit_name(raw) for raw in getattr(args, "units", None) or []]
    tags = getattr(args, "tags", None) or []
    if tags:
        try:
            chosen, others = await sd.resolve(
                bus, tags=tags, session=getattr(args, "session", None)
            )
        except PystemctlError as missing:
            units.append(await _collected_fallback(args, tags, missing))
        else:
            if chosen is None:
                raise PystemctlError("give a unit name or at least one --tag")
            if others:
                print(
                    f"pystemctl: {len(others) + 1} jobs match {', '.join(tags)}; "
                    f"using the newest, {chosen.name} "
                    f"(also: {', '.join(job.name for job in others)})",
                    file=sys.stderr,
                )
            units.append(chosen.name)
    if not units:
        raise PystemctlError("give a unit name or at least one --tag")
    return units


async def resolve_existing(bus: Bus, args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    """Resolve a target and read its properties, failing if it is not loaded.

    Returns the unit name and its property map, so a caller does not fetch the
    same properties twice.
    """
    name = await resolve_target(bus, args)
    props = await sd.try_unit_properties(bus, name)
    if not props or props.get("LoadState") == "not-found":
        raise PystemctlError(f"Unit {name} not found.")
    return name, props


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


class NoTimeout:
    """A drop-in for ``anyio.move_on_after`` that never fires."""

    def __enter__(self) -> "NoTimeout":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def jsonable(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


@dataclass
class WatchOutcome:
    """What a watcher learns before it stops.

    ``matched`` is set when a pattern was found. ``props`` holds the unit
    properties read at the end, which carry the result and exit status.
    """

    matched: bool = False
    props: dict[str, Any] = field(default_factory=dict)


def unit_groups(units: Sequence[str], scope: Scope) -> tuple[list[str], list[str]]:
    """Split unit names into the (system, user) pair the journal reader wants."""
    if scope is Scope.SYSTEM:
        return list(units), []
    return [], list(units)


def exit_code_from(props: dict[str, Any]) -> int:
    """Map a stopped unit's properties to the shell exit code for its result.

    A unit killed by a signal, timed out, or that failed for another reason
    reports a result other than "success" but no exit-code status, so it maps
    to 1. Only a service's own non-zero exit carries its number.
    """
    result = props.get("Result")
    status = props.get("ExecMainStatus")
    if result == "exit-code" and isinstance(status, int) and status:
        return status
    return 0 if result in (None, "success") else 1


async def follow_matching(
    name: str,
    args: argparse.Namespace,
    outcome: WatchOutcome,
    group: anyio.abc.TaskGroup,
    *,
    replay: int,
    stop_on_match: bool,
    skip_notices: bool = True,
) -> None:
    """Stream a unit's output into stdout, recording a pattern match.

    Shared by ``wait`` and ``tail``. With ``stop_on_match`` the first matching
    line ends the watch; otherwise every line is printed and only a match is
    recorded. The pattern is matched against each entry's MESSAGE, so --grep
    means the same thing whatever the output mode is. A set pattern matches
    the manager's lifecycle lines too, so waiting on an expected notice
    still works; without one they stay hidden.
    """
    system_units, user_units = unit_groups([name], args.scope)
    async for line in jr.follow_lines(
        system_units=system_units,
        user_units=user_units,
        pattern=args.grep,
        mode="json" if getattr(args, "json", False) else "cat",
        since_lines=replay,
        skip_notices=skip_notices,
    ):
        print(line, flush=True)
        if args.grep:
            outcome.matched = True
            if stop_on_match:
                group.cancel_scope.cancel()
                return
    group.cancel_scope.cancel()
