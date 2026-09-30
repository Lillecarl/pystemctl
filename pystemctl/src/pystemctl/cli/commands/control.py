"""Lifecycle commands: start, stop, restart, reload, rm."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Awaitable, Callable

from jeepney.wrappers import DBusErrorResponse

from ... import systemd as sd
from ...bus import Bus

_Action = Callable[[Bus, str], Awaitable[str]]


async def cmd_start(bus: Bus, args: argparse.Namespace) -> int:
    return await _unit_action(bus, args, sd.start_unit)


async def cmd_stop(bus: Bus, args: argparse.Namespace) -> int:
    return await _unit_action(bus, args, sd.stop_unit)


async def cmd_restart(bus: Bus, args: argparse.Namespace) -> int:
    return await _unit_action(bus, args, sd.restart_unit)


async def cmd_reload(bus: Bus, args: argparse.Namespace) -> int:
    return await _unit_action(bus, args, sd.reload_unit)


async def _unit_action(bus: Bus, args: argparse.Namespace, action: _Action) -> int:
    results: list[dict[str, str]] = []
    exit_code = 0
    for raw in args.units:
        name = sd.normalize_unit_name(raw)
        try:
            job = await action(bus, name)
        except DBusErrorResponse as error:
            results.append({"unit": name, "job_state": "failed", "error": str(error)})
            if not args.json:
                print(f"pystemctl: {name}: {error}", file=sys.stderr)
            exit_code = 1
            continue
        state = await sd.wait_job(bus, job)
        results.append({"unit": name, "job_state": state})
        if not args.json:
            print(f"{name}: {state}")
        if state != "done":
            exit_code = 1
    if args.json:
        print(json.dumps(results))
    return exit_code


async def cmd_rm(bus: Bus, args: argparse.Namespace) -> int:
    removed: list[str] = []
    for raw in args.units:
        name = sd.normalize_unit_name(raw)
        props = await sd.try_unit_properties(bus, name)
        if props and props.get("ActiveState") not in {"inactive", None}:
            job = await sd.stop_unit(bus, name)
            await sd.wait_job(bus, job)
        await sd.reset_failed_unit(bus, name)
        removed.append(name)
        if not args.json:
            print(f"Removed {name}.")
    if args.json:
        print(json.dumps([{"unit": name, "removed": True} for name in removed]))
    return 0
