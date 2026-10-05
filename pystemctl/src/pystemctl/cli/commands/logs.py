"""Show journal entries, optionally for specific units."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from ... import journal as jr
from ...bus import Bus, Scope
from ..helpers import resolve_units, tail_count


async def cmd_logs(bus: Bus, args: argparse.Namespace) -> int:
    units = await resolve_units(bus, args)
    system_units, user_units = unit_groups(units, args.scope)
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


def unit_groups(units: Sequence[str], scope: Scope) -> tuple[list[str], list[str]]:
    if scope is Scope.SYSTEM:
        return list(units), []
    return [], list(units)


async def journal_tail(unit: str, lines: int, scope: Scope) -> list[str]:
    system_units, user_units = unit_groups([unit], scope)
    reader = jr.open_reader(system_units=system_units, user_units=user_units)
    result: list[str] = []
    async for entry in jr.entries(reader, tail=lines):
        result.append(jr.format_entry(entry, "short"))
    return result
