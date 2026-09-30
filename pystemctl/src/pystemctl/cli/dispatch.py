"""Turn parsed arguments into work."""

from __future__ import annotations

import argparse

from .. import journal as jr
from .. import systemd as sd
from ..bus import Scope, connect
from .helpers import tail_count


async def dispatch(args: argparse.Namespace) -> int:
    scope = getattr(args, "scope", Scope.USER)
    async with connect(scope) as bus:
        return await args.handler(bus, args)


async def journal_dispatch(args: argparse.Namespace) -> int:
    system_units = [sd.normalize_unit_name(unit) for unit in args.system_units]
    user_units = [sd.normalize_unit_name(unit) for unit in args.user_units]
    since = jr.parse_timestamp(args.since) if args.since else None
    until = jr.parse_timestamp(args.until) if args.until else None
    priority = jr.priority_value(args.priority) if args.priority else None
    await jr.print_entries(
        system_units=system_units,
        user_units=user_units,
        tail=tail_count(args.lines, args.follow, since),
        follow=args.follow,
        since=since,
        until=until,
        priority=priority,
        boot=args.boot,
        mode="json" if args.json else args.output,
    )
    return 0
