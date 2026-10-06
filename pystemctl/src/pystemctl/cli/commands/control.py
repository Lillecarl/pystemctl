"""Lifecycle commands: start, stop, restart, reload, rm."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from jeepney.wrappers import DBusErrorResponse

from ... import systemd as sd
from ...bus import Bus
from ...errors import UnitNotFoundError, is_no_such_unit
from ..args import UnitsArgs
from ..helpers import has_journal_trace, note_foreign_session
from ..output import emit_json, warn

_Action = Callable[[Bus, str], Awaitable[str]]


async def cmd_start(bus: Bus, args: UnitsArgs) -> int:
    return await _unit_action(bus, args, sd.start_unit)


async def cmd_stop(bus: Bus, args: UnitsArgs) -> int:
    return await _unit_action(bus, args, sd.stop_unit)


async def cmd_restart(bus: Bus, args: UnitsArgs) -> int:
    return await _unit_action(bus, args, sd.restart_unit)


async def cmd_reload(bus: Bus, args: UnitsArgs) -> int:
    return await _unit_action(bus, args, sd.reload_unit)


async def _unit_action(bus: Bus, args: UnitsArgs, action: _Action) -> int:
    results: list[dict[str, str]] = []
    exit_code = 0
    for raw in args.units:
        name = sd.normalize_unit_name(raw)
        props = await sd.try_unit_properties(bus, name)
        if not args.json:
            note_foreign_session(name, props)
        try:
            job = await action(bus, name)
        except DBusErrorResponse as error:
            if is_no_such_unit(error):
                message = str(UnitNotFoundError(name))
            else:
                message = f"{name}: {error}"
            results.append({"unit": name, "job_state": "failed", "error": message})
            if not args.json:
                warn(message)
            exit_code = 1
            continue
        state = await sd.wait_job(bus, job)
        results.append({"unit": name, "job_state": state})
        if not args.json:
            print(f"{name}: {state}")
        if state != "done":
            exit_code = 1
    if args.json:
        emit_json(results)
    return exit_code


async def cmd_rm(bus: Bus, args: UnitsArgs) -> int:
    removed: list[dict[str, object]] = []
    exit_code = 0
    for raw in args.units:
        name = sd.normalize_unit_name(raw)
        props = await sd.try_unit_properties(bus, name)
        if not props or props.get("LoadState") == "not-found":
            if await has_journal_trace(name, args.scope):
                # Ran before, collected since: the end state rm ensures
                # already holds, so this is success. A name with no journal
                # trace below stays an error: that is a typo, and success
                # there would hide a cleanup that never happened.
                removed.append({"unit": name, "removed": True})
                if not args.json:
                    warn(f"{name}: already finished and was collected; nothing to remove.")
                continue
            message = str(UnitNotFoundError(name))
            removed.append({"unit": name, "removed": False, "error": message})
            if not args.json:
                warn(message)
            exit_code = 1
            continue
        if not args.json:
            note_foreign_session(name, props)
        if props.get("ActiveState") not in {"inactive", None}:
            job = await sd.stop_unit(bus, name)
            await sd.wait_job(bus, job)
        await sd.reset_failed_unit(bus, name)
        removed.append({"unit": name, "removed": True})
        if not args.json:
            print(f"Removed {name}.")
    if args.json:
        emit_json(removed)
    return exit_code
