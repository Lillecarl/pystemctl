"""State and file queries: is-*, enable, disable, cat, show, daemon-reload."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from jeepney.wrappers import DBusErrorResponse

from ... import systemd as sd
from ...bus import MANAGER_INTERFACE, SYSTEMD_PATH, Bus
from ...errors import PystemctlError
from ...render import format_property_value
from ..helpers import jsonable


def _query_states(
    args: argparse.Namespace,
    results: Sequence[tuple[str, str]],
    *,
    expected: set[str],
    exit_code: int,
) -> int:
    """Print a per-unit state, as lines or as JSON, and set the exit status.

    The exit status is non-zero when any unit is not in ``expected``, and is
    reported the same way whether or not JSON was asked for.
    """
    failed = any(state not in expected for _name, state in results)
    if args.json:
        print(json.dumps([{"unit": name, "state": state} for name, state in results]))
    elif len(results) > 1:
        for name, state in results:
            print(f"{name}: {state}")
    else:
        for _name, state in results:
            print(state)
    return exit_code if failed else 0


async def cmd_is_active(bus: Bus, args: argparse.Namespace) -> int:
    results: list[tuple[str, str]] = []
    for raw in args.units:
        name = sd.normalize_unit_name(raw)
        results.append((name, await sd.unit_active_state(bus, name)))
    return _query_states(args, results, expected={"active"}, exit_code=3)


async def cmd_is_failed(bus: Bus, args: argparse.Namespace) -> int:
    results: list[tuple[str, str]] = []
    for raw in args.units:
        name = sd.normalize_unit_name(raw)
        results.append((name, await sd.unit_active_state(bus, name)))
    return _query_states(args, results, expected={"failed"}, exit_code=1)


async def cmd_is_enabled(bus: Bus, args: argparse.Namespace) -> int:
    enabled_states = {"enabled", "enabled-runtime", "linked", "linked-runtime", "alias"}
    results: list[tuple[str, str]] = []
    for raw in args.units:
        name = sd.normalize_unit_name(raw)
        try:
            state = await sd.get_unit_file_state(bus, name)
        except DBusErrorResponse:
            state = "not-found"
        results.append((name, state or "not-found"))
    return _query_states(args, results, expected=enabled_states, exit_code=1)


async def cmd_enable(bus: Bus, args: argparse.Namespace) -> int:
    report: list[dict[str, object]] = []
    for raw in args.units:
        name = sd.normalize_unit_name(raw)
        changes = await sd.enable_unit(bus, name)
        report.append({"unit": name, "changes": [list(change) for change in changes]})
        if args.json:
            continue
        if not changes:
            print(f"{name} was already enabled.")
        for change_type, _filename, destination in changes:
            if change_type == "symlink":
                print(f"Created symlink {destination} -> {name}")
            else:
                print(f"{change_type} {destination}")
    if args.json:
        print(json.dumps(report))
    return 0


async def cmd_disable(bus: Bus, args: argparse.Namespace) -> int:
    report: list[dict[str, object]] = []
    for raw in args.units:
        name = sd.normalize_unit_name(raw)
        changes = await sd.disable_unit(bus, name)
        report.append({"unit": name, "changes": [list(change) for change in changes]})
        if args.json:
            continue
        for change_type, _filename, destination in changes:
            if change_type == "unlink":
                print(f"Removed {destination}")
            else:
                print(f"{change_type} {destination}")
    if args.json:
        print(json.dumps(report))
    return 0


async def cmd_cat(bus: Bus, args: argparse.Namespace) -> int:
    report: list[dict[str, object]] = []
    for raw in args.units:
        name = sd.normalize_unit_name(raw)
        props = await sd.unit_properties(bus, name)
        paths: list[str] = []
        fragment = props.get("FragmentPath")
        if fragment:
            paths.append(fragment)
        paths.extend(props.get("DropInPaths", []))
        if not paths:
            report.append({"unit": name, "files": []})
            if not args.json:
                print(f"No files found for {name}.", file=sys.stderr)
            continue
        files: list[dict[str, str]] = []
        for path in paths:
            try:
                content = Path(path).read_text()
            except OSError as error:
                if not args.json:
                    print(f"# {path}\n# unable to read: {error}", file=sys.stderr)
                continue
            files.append({"path": path, "content": content})
            if not args.json:
                print(f"# {path}")
                print(content)
        report.append({"unit": name, "files": files})
    if args.json:
        print(json.dumps(report))
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


async def cmd_daemon_reload(bus: Bus, args: argparse.Namespace) -> int:
    await sd.reload_manager(bus)
    if args.json:
        print(json.dumps({"reloaded": True}))
    return 0
