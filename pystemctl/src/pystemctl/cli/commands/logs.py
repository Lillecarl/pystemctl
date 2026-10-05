"""Show journal entries, optionally for specific units."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from ... import journal as jr
from ... import systemd as sd
from ...bus import Bus, Scope
from ..helpers import has_journal_trace, resolve_units, tail_count


async def cmd_logs(bus: Bus, args: argparse.Namespace) -> int:
    units = await resolve_units(bus, args)
    units = await _drop_unknown(bus, args, units)
    if not units:
        return 1
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
        skip_notices=not args.json,
    )
    return 0


async def _drop_unknown(bus: Bus, args: argparse.Namespace, units: list[str]) -> list[str]:
    """Remove named units that never ran, failing the way ``wait`` does.

    Only positionals are checked: a tag already resolved to something real,
    or to a collected job whose journal outlives it. A collected job stays,
    because its log lines are exactly what was asked for; a name with no
    journal trace is a typo, and answering it with empty output and success
    would hide that.
    """
    explicit = {sd.normalize_unit_name(raw) for raw in getattr(args, "units", None) or []}
    kept = []
    for name in units:
        if name in explicit:
            props = await sd.try_unit_properties(bus, name)
            if not props or props.get("LoadState") == "not-found":
                scope = getattr(args, "scope", Scope.USER)
                if await has_journal_trace(name, scope):
                    kept.append(name)
                    continue
                print(f"pystemctl: Unit {name} not found.", file=sys.stderr)
                continue
        kept.append(name)
    return kept


def unit_groups(units: Sequence[str], scope: Scope) -> tuple[list[str], list[str]]:
    if scope is Scope.SYSTEM:
        return list(units), []
    return [], list(units)


async def journal_tail(unit: str, lines: int, scope: Scope) -> list[str]:
    system_units, user_units = unit_groups([unit], scope)
    reader = jr.open_reader(system_units=system_units, user_units=user_units)
    result: list[str] = []
    async for entry in jr.entries(reader, tail=lines, skip_notices=True):
        result.append(jr.format_entry(entry, "short"))
    return result
