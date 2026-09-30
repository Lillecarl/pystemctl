"""State and file queries: is-*, enable, disable, cat, show, daemon-reload."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jeepney.wrappers import DBusErrorResponse

from ... import systemd as sd
from ...bus import MANAGER_INTERFACE, SYSTEMD_PATH, Bus
from ...errors import PystemctlError
from ...render import format_property_value
from ..helpers import jsonable


async def cmd_is_active(bus: Bus, args: argparse.Namespace) -> int:
    exit_code = 0
    for raw in args.units:
        state = await sd.unit_active_state(bus, sd.normalize_unit_name(raw))
        print(state)
        if state != "active":
            exit_code = 3
    return exit_code


async def cmd_is_failed(bus: Bus, args: argparse.Namespace) -> int:
    exit_code = 0
    for raw in args.units:
        state = await sd.unit_active_state(bus, sd.normalize_unit_name(raw))
        print("failed" if state == "failed" else state)
        if state != "failed":
            exit_code = 1
    return exit_code


async def cmd_is_enabled(bus: Bus, args: argparse.Namespace) -> int:
    enabled_states = {"enabled", "enabled-runtime", "linked", "linked-runtime", "alias"}
    exit_code = 0
    for raw in args.units:
        name = sd.normalize_unit_name(raw)
        try:
            state = await sd.get_unit_file_state(bus, name)
        except DBusErrorResponse:
            state = "not-found"
        print(state or "not-found")
        if state not in enabled_states:
            exit_code = 1
    return exit_code


async def cmd_enable(bus: Bus, args: argparse.Namespace) -> int:
    for raw in args.units:
        name = sd.normalize_unit_name(raw)
        changes = await sd.enable_unit(bus, name)
        if not changes:
            print(f"{name} was already enabled.")
        for change_type, _filename, destination in changes:
            if change_type == "symlink":
                print(f"Created symlink {destination} -> {name}")
            else:
                print(f"{change_type} {destination}")
    return 0


async def cmd_disable(bus: Bus, args: argparse.Namespace) -> int:
    for raw in args.units:
        name = sd.normalize_unit_name(raw)
        changes = await sd.disable_unit(bus, name)
        for change_type, _filename, destination in changes:
            if change_type == "unlink":
                print(f"Removed {destination}")
            else:
                print(f"{change_type} {destination}")
    return 0


async def cmd_cat(bus: Bus, args: argparse.Namespace) -> int:
    for raw in args.units:
        name = sd.normalize_unit_name(raw)
        props = await sd.unit_properties(bus, name)
        paths: list[str] = []
        fragment = props.get("FragmentPath")
        if fragment:
            paths.append(fragment)
        paths.extend(props.get("DropInPaths", []))
        if not paths:
            print(f"No files found for {name}.", file=sys.stderr)
            continue
        for path in paths:
            print(f"# {path}")
            try:
                print(Path(path).read_text())
            except OSError as error:
                print(f"# unable to read: {error}", file=sys.stderr)
    return 0


async def cmd_show(bus: Bus, args: argparse.Namespace) -> int:
    targets: list[str | None] = [sd.normalize_unit_name(unit) for unit in args.units] or [None]
    wanted = getattr(args, "properties", None) or None
    for target in targets:
        if target is None:
            props = await bus.get_all(SYSTEMD_PATH, MANAGER_INTERFACE)
        else:
            props = await sd.unit_properties(bus, target)

        if wanted is not None:
            missing = [name for name in wanted if name not in props]
            if missing:
                raise PystemctlError(
                    f"{target or 'manager'}: no such property: {', '.join(missing)}"
                )
            props = {name: props[name] for name in wanted}

        if args.json:
            print(json.dumps({key: jsonable(value) for key, value in props.items()}, default=str))
            continue
        if target is not None and wanted is None:
            print(f"# {target}")
        for key in sorted(props) if wanted is None else wanted:
            print(f"{key}={format_property_value(props[key])}")
    return 0


async def cmd_daemon_reload(bus: Bus, _args: argparse.Namespace) -> int:
    await sd.reload_manager(bus)
    return 0
