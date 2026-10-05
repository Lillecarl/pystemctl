"""Show journal entries, optionally for specific units."""

from __future__ import annotations

from ... import journal as jr
from ... import systemd as sd
from ...bus import Bus, Scope
from ...errors import UnitNotFoundError
from ..args import LogsArgs
from ..helpers import (
    Target,
    TargetHow,
    has_journal_trace,
    resolve_many,
    tail_count,
    unit_groups,
)
from ..output import warn


async def cmd_logs(bus: Bus, args: LogsArgs) -> int:
    targets = await resolve_many(bus, args)
    units = await _drop_unknown(bus, targets, args.scope)
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


async def _drop_unknown(bus: Bus, targets: list[Target], scope: Scope) -> list[str]:
    """Remove named units that never ran, failing the way ``wait`` does.

    Only explicit names are checked: a tag already resolved to something
    real, or to a collected job whose journal outlives it. A collected job
    stays, because its log lines are exactly what was asked for; a name
    with no journal trace is a typo, and answering it with empty output
    and success would hide that.
    """
    kept = []
    for target in targets:
        if target.how is TargetHow.EXPLICIT:
            props = await sd.try_unit_properties(bus, target.name)
            if not props or props.get("LoadState") == "not-found":
                if await has_journal_trace(target.name, scope):
                    kept.append(target.name)
                    continue
                warn(UnitNotFoundError(target.name))
                continue
        kept.append(target.name)
    return kept


async def journal_tail(unit: str, lines: int, scope: Scope) -> list[str]:
    system_units, user_units = unit_groups([unit], scope)
    reader = jr.open_reader(system_units=system_units, user_units=user_units)
    result: list[str] = []
    async for entry in jr.entries(reader, tail=lines, skip_notices=True):
        result.append(jr.format_entry(entry, "short"))
    return result
