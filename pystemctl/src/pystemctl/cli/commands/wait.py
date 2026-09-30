"""Wait on a unit, optionally until a journal line matches."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Any

import anyio

from ... import journal as jr
from ... import systemd as sd
from ...bus import Bus, Scope
from ...errors import PystemctlError
from ..helpers import jsonable


DEFAULT_REPLAY = 200


@dataclass
class _Outcome:
    props: dict[str, Any] = field(default_factory=dict)
    matched: bool = False


async def cmd_wait(bus: Bus, args: argparse.Namespace) -> int:
    name = sd.normalize_unit_name(args.unit)
    props = await sd.try_unit_properties(bus, name)
    if not props or props.get("LoadState") == "not-found":
        raise PystemctlError(f"Unit {name} not found.")

    outcome = _Outcome()
    scope = anyio.move_on_after(args.timeout) if args.timeout is not None else _NoTimeout()
    with scope:
        if args.grep:
            # Whichever finishes first ends the wait: the pattern match, or the
            # unit stopping. Whichever loses is cancelled by the group exit.
            async with anyio.create_task_group() as group:
                group.start_soon(_until_finished_then_cancel, bus, name, outcome, group)
                group.start_soon(_until_pattern_then_cancel, name, args, outcome, group)
        else:
            outcome.props = await sd.wait_until_finished(bus, name)

    if not outcome.props:
        outcome.props = await sd.try_unit_properties(bus, name)
    return _report(args, name, outcome)


async def _until_finished_then_cancel(
    bus: Bus, name: str, outcome: _Outcome, group: anyio.abc.TaskGroup
) -> None:
    outcome.props = await sd.wait_until_finished(bus, name)
    group.cancel_scope.cancel()


async def _until_pattern_then_cancel(
    name: str, args: argparse.Namespace, outcome: _Outcome, group: anyio.abc.TaskGroup
) -> None:
    system_units, user_units = _unit_groups([name], args.scope)
    # A watcher is usually attached after the job starts, so replay recent
    # output by default; starting at the tail would miss what already printed.
    since_lines = args.lines if args.lines is not None else DEFAULT_REPLAY
    async for line in jr.follow_lines(
        system_units=system_units,
        user_units=user_units,
        pattern=args.grep,
        since_lines=since_lines,
    ):
        print(line, flush=True)
        outcome.matched = True
        group.cancel_scope.cancel()
        return


def _unit_groups(units: list[str], scope: Scope) -> tuple[list[str], list[str]]:
    if scope is Scope.SYSTEM:
        return units, []
    return [], units


def _report(args: argparse.Namespace, name: str, outcome: _Outcome) -> int:
    result = outcome.props.get("Result")
    status = outcome.props.get("ExecMainStatus")

    # A collecting unit is unloaded the moment it stops, which resets the
    # .service interface -- Result reads back "success" and Type an empty
    # string. A stale success is worse than no answer, so treat the reset
    # interface as "no result recorded" rather than reporting a false zero.
    if not outcome.matched and not outcome.props.get("Type"):
        print(
            f"pystemctl: {name}: no result recorded; the unit was collected on "
            "stop, which discards its exit status (start it with a --tag, or "
            "with --no-collect, to keep the result)",
            file=sys.stderr,
        )
        return 1

    if args.json:
        print(
            json.dumps(
                jsonable(
                    {
                        "unit": name,
                        "active_state": outcome.props.get("ActiveState"),
                        "result": result,
                        "status": status,
                        "matched": outcome.matched,
                    }
                )
            )
        )
    elif outcome.matched:
        print(f"pystemctl: {name}: pattern matched", file=sys.stderr)

    if outcome.matched:
        return 0
    if result == "exit-code" and isinstance(status, int) and status:
        return status
    if result not in (None, "success"):
        return 1
    return 0


class _NoTimeout:
    def __enter__(self) -> "_NoTimeout":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    cancel_called = False
