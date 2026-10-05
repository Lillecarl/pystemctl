"""Wait on a unit, optionally until a journal line matches."""

from __future__ import annotations

import argparse
import json
import sys

import anyio

from ... import systemd as sd
from ...bus import Bus
from ..helpers import (
    NoTimeout,
    WatchOutcome,
    exit_code_from,
    follow_matching,
    jsonable,
    resolve_existing,
)

DEFAULT_REPLAY = 200


async def cmd_wait(bus: Bus, args: argparse.Namespace) -> int:
    name, _ = await resolve_existing(bus, args)

    outcome = WatchOutcome()
    scope = anyio.move_on_after(args.timeout) if args.timeout is not None else NoTimeout()
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
    bus: Bus, name: str, outcome: WatchOutcome, group: anyio.abc.TaskGroup
) -> None:
    outcome.props = await sd.wait_until_finished(bus, name)
    group.cancel_scope.cancel()


async def _until_pattern_then_cancel(
    name: str, args: argparse.Namespace, outcome: WatchOutcome, group: anyio.abc.TaskGroup
) -> None:
    # A watcher is usually attached after the job starts, so replay recent
    # output by default; starting at the tail would miss what already printed.
    replay = args.lines if args.lines is not None else DEFAULT_REPLAY
    await follow_matching(
        name, args, outcome, group, replay=replay, stop_on_match=True,
        skip_notices=False,
    )


def _report(args: argparse.Namespace, name: str, outcome: WatchOutcome) -> int:
    result = outcome.props.get("Result")
    status = outcome.props.get("ExecMainStatus")

    code = 0 if outcome.matched else exit_code_from(outcome.props)

    payload = {
        "unit": name,
        "active_state": outcome.props.get("ActiveState"),
        "result": result,
        "status": status,
        "matched": outcome.matched,
        "exit_code": code,
    }

    if args.json:
        print(json.dumps(jsonable(payload)))
    elif outcome.matched:
        print(f"pystemctl: {name}: pattern matched", file=sys.stderr)

    return code
