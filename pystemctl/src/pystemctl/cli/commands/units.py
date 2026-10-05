"""Inspect units: list, list-unit-files, and status."""

from __future__ import annotations

import argparse
import json
import os

from ... import systemd as sd
from ...bus import Bus
from ...errors import UnitNotFound
from ...render import format_table, format_unit_status
from ..helpers import jsonable, resolve_units, unit_payload, unit_payload_from_props
from .logs import journal_tail


def _visible(unit: sd.Unit) -> bool:
    if unit.job_id > 0:
        return True
    if unit.following:
        return False
    return unit.active_state != "inactive"


async def cmd_list(bus: Bus, args: argparse.Namespace) -> int:
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
        print(json.dumps([unit_payload(unit) for unit in units]))
    else:
        rows = [
            [unit.name, unit.load_state, unit.active_state, unit.sub_state, unit.description]
            for unit in units
        ]
        print(format_table(["UNIT", "LOAD", "ACTIVE", "SUB", "DESCRIPTION"], rows))
    return 0


async def cmd_list_unit_files(bus: Bus, args: argparse.Namespace) -> int:
    files = await sd.list_unit_files(bus)
    if args.type:
        suffix = args.type if args.type.startswith(".") else f".{args.type}"
        files = [(path, state) for path, state in files if path.endswith(suffix)]
    if args.state:
        files = [(path, state) for path, state in files if state == args.state]
    files.sort(key=lambda item: os.path.basename(item[0]))

    if args.json:
        print(json.dumps([{"unit_file": os.path.basename(p), "state": s} for p, s in files]))
    else:
        rows = [[os.path.basename(path), state] for path, state in files]
        print(format_table(["UNIT FILE", "STATE"], rows))
    return 0


async def cmd_status(bus: Bus, args: argparse.Namespace) -> int:
    exit_code = 0
    for name in await resolve_units(bus, args):
        try:
            props = await sd.unit_properties(bus, name)
        except UnitNotFound:
            print(f"Unit {name} could not be found.")
            exit_code = max(exit_code, 4)
            continue

        if props.get("LoadState") == "not-found":
            exit_code = max(exit_code, 3)
            if args.json:
                payload = unit_payload_from_props(name, props)
                if not args.no_journal:
                    payload["journal"] = await journal_tail(name, args.lines, args.scope)
                print(json.dumps(payload, default=str, ensure_ascii=False))
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
            print(json.dumps(payload, default=str, ensure_ascii=False))
            continue

        print(format_unit_status(name, props))
        if not args.no_journal:
            for line in await journal_tail(name, args.lines, args.scope):
                print(f"    {line}")
        print()
    return exit_code
