"""Lifecycle commands: start, stop, restart, reload, rm."""

from __future__ import annotations

import argparse
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
    exit_code = 0
    for raw in args.units:
        name = sd.normalize_unit_name(raw)
        try:
            job = await action(bus, name)
        except DBusErrorResponse as error:
            print(f"pystemctl: {name}: {error}", file=sys.stderr)
            exit_code = 1
            continue
        state = await sd.wait_job(bus, job)
        print(f"{name}: {state}")
        if state != "done":
            exit_code = 1
    return exit_code


async def cmd_rm(bus: Bus, args: argparse.Namespace) -> int:
    for raw in args.units:
        name = sd.normalize_unit_name(raw)
        props = await sd.try_unit_properties(bus, name)
        if props and props.get("ActiveState") not in {"inactive", None}:
            job = await sd.stop_unit(bus, name)
            await sd.wait_job(bus, job)
        await sd.reset_failed_unit(bus, name)
        print(f"Removed {name}.")
    return 0
