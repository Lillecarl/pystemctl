"""Follow a unit's output until it stops or a line matches."""

from __future__ import annotations

import argparse
import re

import anyio

from ... import journal as jr
from ... import systemd as sd
from ...bus import Bus
from ..helpers import (
    TIMEOUT_EXIT_CODE,
    NoTimeout,
    WatchOutcome,
    exit_code_from,
    resolve_existing,
    timeout_note,
    unit_groups,
    watch_unit,
)
from ..output import warn

DEFAULT_REPLAY = 200


async def cmd_tail(bus: Bus, args: argparse.Namespace) -> int:
    name, props = await resolve_existing(bus, args)

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
        timeout_note(args, name)
        if args.until_exit:
            return TIMEOUT_EXIT_CODE
        if args.grep and not outcome.matched:
            return 1
        return 0

    return _report(args, name, outcome)


async def _replay(name: str, args: argparse.Namespace, replay: int) -> None:
    """Print the last ``replay`` lines and return, like a plain tail."""
    system_units, user_units = unit_groups([name], args.scope)
    pattern = re.compile(args.grep) if args.grep else None
    reader = jr.open_reader(system_units=system_units, user_units=user_units)
    async for entry in jr.entries(reader, tail=replay, skip_notices=True):
        if args.json:
            # A whole entry, so a caller gets fields the plain line drops.
            if pattern is None or pattern.search(jr.message_text(entry)):
                print(jr.format_entry(entry, "json"), flush=True)
            continue
        line = jr.format_entry(entry, "cat")
        if pattern is None or pattern.search(line):
            print(line, flush=True)


def _report(args: argparse.Namespace, name: str, outcome: WatchOutcome) -> int:
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
