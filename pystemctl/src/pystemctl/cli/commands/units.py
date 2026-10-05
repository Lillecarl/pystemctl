"""Inspect units: list, list-unit-files, and status."""

from __future__ import annotations

import os

from ... import systemd as sd
from ...bus import Bus
from ...errors import UnitNotFoundError
from ...render import format_table, format_unit_status
from ..args import ListArgs, ListFilesArgs, StatusArgs
from ..helpers import (
    has_journal_trace,
    resolve_many,
    unit_payload,
    unit_payload_from_props,
)
from ..output import emit_json
from .logs import journal_tail


def _visible(unit: sd.Unit) -> bool:
    if unit.job_id > 0:
        return True
    if unit.following:
        return False
    return unit.active_state != "inactive"


async def cmd_list(bus: Bus, args: ListArgs) -> int:
    units = await sd.list_units(bus)
    if not args.all:
        units = [unit for unit in units if _visible(unit)]
    if args.type:
        suffix = args.type if args.type.startswith(".") else f".{args.type}"
        units = [unit for unit in units if unit.name.endswith(suffix)]
    if args.state:
        units = [unit for unit in units if args.state in (unit.active_state, unit.sub_state)]
    if args.ephemeral:
        units = [unit for unit in units if await sd.is_transient(bus, unit)]
    units.sort(key=lambda unit: unit.name)

    if args.json:
        emit_json([unit_payload(unit) for unit in units])
    else:
        rows = [
            [unit.name, unit.load_state, unit.active_state, unit.sub_state, unit.description]
            for unit in units
        ]
        print(format_table(["UNIT", "LOAD", "ACTIVE", "SUB", "DESCRIPTION"], rows))
    return 0


async def cmd_list_unit_files(bus: Bus, args: ListFilesArgs) -> int:
    files = await sd.list_unit_files(bus)
    if args.type:
        suffix = args.type if args.type.startswith(".") else f".{args.type}"
        files = [(path, state) for path, state in files if path.endswith(suffix)]
    if args.state:
        files = [(path, state) for path, state in files if state == args.state]
    files.sort(key=lambda item: os.path.basename(item[0]))

    if args.json:
        emit_json([{"unit_file": os.path.basename(p), "unit_file_state": s} for p, s in files])
    else:
        rows = [[os.path.basename(path), state] for path, state in files]
        print(format_table(["UNIT FILE", "STATE"], rows))
    return 0


async def cmd_status(bus: Bus, args: StatusArgs) -> int:
    exit_code = 0
    for target in await resolve_many(bus, args):
        name = target.name
        try:
            props = await sd.unit_properties(bus, name)
        except UnitNotFoundError as missing:
            print(missing)
            exit_code = max(exit_code, missing.exit_code)
            continue

        if props.get("LoadState") == "not-found":
            # Not loaded covers two cases: a job that finished and was
            # collected, and a name that never ran at all. Only the first
            # one finished anything; the journal tells them apart.
            trace = await has_journal_trace(name, args.scope)
            exit_code = max(exit_code, 3 if trace else 4)
            if args.json:
                payload = unit_payload_from_props(name, props)
                if not args.no_journal:
                    payload["journal"] = await journal_tail(name, args.lines, args.scope)
                emit_json(payload)
                continue
            if not trace:
                print(UnitNotFoundError(name))
                continue
            print(f"- {name}")
            print("  Collected: finished and unloaded; the result is gone, its logs follow.")
            if not args.no_journal:
                for line in await journal_tail(name, args.lines, args.scope):
                    print(f"    {line}")
            print()
            continue

        active_state = props.get("ActiveState", "inactive")
        exit_code = max(exit_code, 0 if active_state == "active" else 3)

        if args.json:
            payload = unit_payload_from_props(name, props)
            if not args.no_journal:
                payload["journal"] = await journal_tail(name, args.lines, args.scope)
            emit_json(payload)
            continue

        print(format_unit_status(name, props))
        if not args.no_journal:
            for line in await journal_tail(name, args.lines, args.scope):
                print(f"    {line}")
        print()
    return exit_code
