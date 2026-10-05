"""Wait on a unit, optionally until a journal line matches."""

from __future__ import annotations

import anyio

from ... import systemd as sd
from ...bus import Bus
from ..args import WaitArgs
from ..helpers import (
    TIMEOUT_EXIT_CODE,
    NoTimeout,
    WatchOutcome,
    exit_code_from,
    resolve_existing,
    timeout_note,
    watch_unit,
)
from ..output import emit_json, warn

DEFAULT_REPLAY = 200


async def cmd_wait(bus: Bus, args: WaitArgs) -> int:
    name, _ = await resolve_existing(bus, args)

    outcome = WatchOutcome()
    scope = anyio.move_on_after(args.timeout) if args.timeout is not None else NoTimeout()
    with scope:
        if args.grep:
            # Whichever finishes first ends the wait: the pattern match, or
            # the unit stopping. The race cancels its loser inside watch_unit.
            # A watcher usually attaches after the job starts, so replay
            # recent output by default; starting at the tail would miss what
            # already printed.
            replay = args.lines if args.lines is not None else DEFAULT_REPLAY
            await watch_unit(
                bus,
                name,
                args,
                outcome,
                replay=replay,
                stop_on_match=True,
                skip_notices=False,
            )
        else:
            outcome.props = await sd.wait_until_finished(bus, name)

    if outcome.matched:
        return _report(args, name, outcome)
    if args.timeout is not None and getattr(scope, "cancelled_caught", False):
        return _report_timeout(args.timeout, args, name, outcome)
    if not outcome.props:
        outcome.props = await sd.try_unit_properties(bus, name)
    return _report(args, name, outcome)


def _report(args: WaitArgs, name: str, outcome: WatchOutcome) -> int:
    result = outcome.props.get("Result")
    status = outcome.props.get("ExecMainStatus")

    code = 0 if outcome.matched else exit_code_from(outcome.props)

    payload = {
        "unit": name,
        "active_state": outcome.props.get("ActiveState"),
        "result": result,
        "exit_status": status,
        "matched": outcome.matched,
        "exit_code": code,
    }

    if args.json:
        emit_json(payload)
    elif outcome.matched:
        warn(f"{name}: pattern matched")

    return code


def _report_timeout(timeout: float, args: WaitArgs, name: str, outcome: WatchOutcome) -> int:
    """Report a wait that outlived its --timeout.

    The still-running unit keeps running; only the watching stops. Silence
    here would read as success, so this always names the timeout on stderr
    and exits 124, the way ``timeout(1)`` does.
    """
    payload = {
        "unit": name,
        "active_state": outcome.props.get("ActiveState"),
        "result": outcome.props.get("Result"),
        "exit_status": outcome.props.get("ExecMainStatus"),
        "matched": False,
        "timed_out": True,
        "timeout": timeout,
        "exit_code": TIMEOUT_EXIT_CODE,
    }

    if args.json:
        emit_json(payload)
    else:
        timeout_note(timeout, name)
    return TIMEOUT_EXIT_CODE
