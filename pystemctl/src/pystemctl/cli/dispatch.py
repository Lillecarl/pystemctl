"""Turn parsed arguments into work."""

from __future__ import annotations

import argparse

from .. import journal as jr
from .. import systemd as sd
from ..bus import connect
from .args import JournalArgs
from .helpers import tail_count


async def dispatch(args: argparse.Namespace) -> int:
    command = args.args_type.from_namespace(args)
    async with connect(command.scope) as bus:
        return await args.handler(bus, command)


async def journal_dispatch(args: argparse.Namespace) -> int:
    command = JournalArgs.from_namespace(args)
    system_units = [sd.normalize_unit_name(unit) for unit in command.system_units]
    user_units = [sd.normalize_unit_name(unit) for unit in command.user_units]
    since = jr.parse_timestamp(command.since) if command.since else None
    until = jr.parse_timestamp(command.until) if command.until else None
    priority = jr.priority_value(command.priority) if command.priority else None
    await jr.print_entries(
        system_units=system_units,
        user_units=user_units,
        tail=tail_count(command.lines, command.follow, since),
        follow=command.follow,
        since=since,
        until=until,
        priority=priority,
        boot=command.boot,
        mode="json" if command.json else command.output,
    )
    return 0
