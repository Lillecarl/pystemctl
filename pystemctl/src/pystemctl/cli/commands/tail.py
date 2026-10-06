"""Follow a unit's output until it stops or a line matches."""

from __future__ import annotations

import re

import anyio

from ... import journal as jr
from ... import systemd as sd
from ...bus import Bus
from ...errors import PystemctlError, UnitNotFoundError
from ..args import TailArgs
from ..helpers import (
    TIMEOUT_EXIT_CODE,
    NoTimeout,
    WatchOutcome,
    exit_code_from,
    recovered_exit_code,
    resolve_existing,
    timeout_note,
    unit_groups,
    watch_unit,
)
from ..output import warn

DEFAULT_REPLAY = 200


async def cmd_tail(bus: Bus, args: TailArgs) -> int:
    try:
        target, props = await resolve_existing(bus, args)
    except UnitNotFoundError:
        raise
    except PystemctlError as error:
        # Dead unit: replay what the journal holds, then report with the
        # live meanings. grep answers matched-or-not; otherwise the
        # recovered code, or 0 for an explicit -f stream.
        recovered = await recovered_exit_code(args)
        if recovered is None:
            raise
        name, code = recovered
        replay = args.lines if args.lines is not None else DEFAULT_REPLAY
        matched = await _replay(name, args, replay)
        if args.grep is not None:
            return 0 if matched else 1
        if not args.json:
            warn(str(error))
        return code if args.until_exit else 0
    name = target.name

    outcome = WatchOutcome(props=props)
    replay = args.lines if args.lines is not None else DEFAULT_REPLAY

    # Following is asked for with -f, or is implied by wanting the exit status,
    # which cannot be known without observing the unit stop.
    follow = args.follow or args.until_exit

    if not follow:
        await _replay(name, args, replay)
        return 0

    scope = anyio.move_on_after(args.timeout) if args.timeout is not None else NoTimeout()
    with scope:
        await watch_unit(
            bus,
            name,
            args,
            outcome,
            replay=replay,
            stop_on_match=True,
            skip_notices=args.grep is None,
            watch_finish=not sd.unit_finished(props),
        )

    if args.timeout is not None and getattr(scope, "cancelled_caught", False):
        # A bounded follow that runs out of time did not fail, but it did not
        # see the end either. The note always fires; the code follows the
        # mode: --until-exit promises an outcome, --grep promises a match,
        # and a plain follow already printed what arrived.
        timeout_note(args.timeout, name)
        if args.until_exit:
            return TIMEOUT_EXIT_CODE
        if args.grep and not outcome.matched:
            return 1
        return 0

    return _report(args, name, outcome)


async def _replay(name: str, args: TailArgs, replay: int) -> int:
    """Print the last ``replay`` lines and return, like a plain tail.

    Returns how many printed lines matched, so a caller replaying a dead
    unit can answer grep the way the live follow does.
    """
    system_units, user_units = unit_groups([name], args.scope)
    pattern = re.compile(args.grep) if args.grep else None
    reader = jr.open_reader(system_units=system_units, user_units=user_units)
    matched = 0
    async for entry in jr.entries(reader, tail=replay, skip_notices=True):
        if args.json:
            # A whole entry, so a caller gets fields the plain line drops.
            if pattern is None or pattern.search(jr.message_text(entry)):
                print(jr.format_entry(entry, "json"), flush=True)
                matched += 1
            continue
        line = jr.format_entry(entry, "cat")
        if pattern is None or pattern.search(line):
            print(line, flush=True)
            matched += 1
    return matched


def _report(args: TailArgs, name: str, outcome: WatchOutcome) -> int:
    if args.grep:
        return 0 if outcome.matched else 1
    if args.until_exit:
        if not outcome.props.get("Type"):
            warn(
                f"{name}: no result recorded; the unit was collected "
                "on stop, which discards its exit status"
            )
            return 1
        return exit_code_from(outcome.props)
    return 0
