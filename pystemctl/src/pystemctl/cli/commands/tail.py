"""Follow a unit's output until it stops or a line matches."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from typing import Any

import anyio

from ... import journal as jr
from ... import systemd as sd
from ...bus import Bus, Scope
from ...errors import PystemctlError
from ..helpers import resolve_target

DEFAULT_REPLAY = 200


@dataclass
class _Outcome:
    matched: bool = False
    props: dict[str, Any] = field(default_factory=dict)


async def cmd_tail(bus: Bus, args: argparse.Namespace) -> int:
    name = await resolve_target(bus, args)
    props = await sd.try_unit_properties(bus, name)
    if not props or props.get("LoadState") == "not-found":
        raise PystemctlError(f"Unit {name} not found.")

    outcome = _Outcome(props=props)
    replay = args.lines if args.lines is not None else DEFAULT_REPLAY

    # Following is asked for with -f, or is implied by wanting the exit status,
    # which cannot be known without observing the unit stop.
    follow = args.follow or args.until_exit

    if not follow:
        await _replay(name, args, replay)
        return 0

    scope = anyio.move_on_after(args.timeout) if args.timeout is not None else _NoTimeout()
    with scope:
        async with anyio.create_task_group() as group:
            group.start_soon(_stream, name, args, outcome, replay, group)
            if not sd.unit_finished(props):
                group.start_soon(_watch, bus, name, outcome, group)

    return _report(args, name, outcome)


async def _replay(name: str, args: argparse.Namespace, replay: int) -> None:
    """Print the last ``replay`` lines and return, like a plain tail."""
    system_units, user_units = _unit_groups([name], args.scope)
    pattern = re.compile(args.grep) if args.grep else None
    reader = jr.open_reader(system_units=system_units, user_units=user_units)
    async for entry in jr.entries(reader, tail=replay):
        if args.json:
            # A whole entry, so a caller gets fields the plain line drops.
            if pattern is None or pattern.search(jr.entry_message(entry)):
                print(jr.format_entry(entry, "json"), flush=True)
            continue
        line = jr.format_entry(entry, "cat")
        if pattern is None or pattern.search(line):
            print(line, flush=True)


async def _stream(
    name: str,
    args: argparse.Namespace,
    outcome: _Outcome,
    replay: int,
    group: anyio.abc.TaskGroup,
) -> None:
    system_units, user_units = _unit_groups([name], args.scope)
    # --grep matches the plain text of a line even in JSON mode, so the
    # pattern is applied by follow_lines before formatting.
    async for line in jr.follow_lines(
        system_units=system_units,
        user_units=user_units,
        pattern=args.grep,
        mode="json" if args.json else "cat",
        since_lines=replay,
    ):
        print(line, flush=True)
        if args.grep:
            outcome.matched = True
            group.cancel_scope.cancel()
            return
    group.cancel_scope.cancel()


async def _watch(bus: Bus, name: str, outcome: _Outcome, group: anyio.abc.TaskGroup) -> None:
    outcome.props = await sd.wait_until_finished(bus, name)
    group.cancel_scope.cancel()


def _unit_groups(units: list[str], scope: Scope) -> tuple[list[str], list[str]]:
    if scope is Scope.SYSTEM:
        return units, []
    return [], units


def _report(args: argparse.Namespace, name: str, outcome: _Outcome) -> int:
    if args.grep:
        return 0 if outcome.matched else 1
    if args.until_exit:
        result = outcome.props.get("Result")
        status = outcome.props.get("ExecMainStatus")
        if not outcome.props.get("Type"):
            print(
                f"pystemctl: {name}: no result recorded; the unit was collected "
                "on stop, which discards its exit status",
                file=sys.stderr,
            )
            return 1
        if result == "exit-code" and isinstance(status, int) and status:
            return status
        return 0 if result in (None, "success") else 1
    return 0


class _NoTimeout:
    def __enter__(self) -> "_NoTimeout":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    cancel_called = False
