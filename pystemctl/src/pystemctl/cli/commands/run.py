"""Start an ephemeral unit from a command."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from typing import Any

from jeepney.wrappers import DBusErrorResponse

from ... import profiles
from ... import systemd as sd
from ...bus import Bus
from ...errors import PystemctlError
from ...systemd.tags import session_id
from ..helpers import emit, parse_environment, parse_property, strip_separator


def _load_profile(args: argparse.Namespace) -> profiles.Profile | None:
    if not args.profile:
        return None
    available = profiles.load_profiles()
    if args.profile not in available:
        names = ", ".join(sorted(available)) or "none defined"
        raise PystemctlError(f"profile {args.profile!r} not found (available: {names})")
    return profiles.apply_cli_overrides(available[args.profile], args)


async def cmd_run(bus: Bus, args: argparse.Namespace) -> int:
    command = strip_separator(args.command)
    if not command:
        raise PystemctlError("no command given; use: pystemctl run [options] -- COMMAND [ARGS...]")

    profile = _load_profile(args)

    if args.shell:
        argv = [shutil.which("sh") or "/bin/sh", "-c", " ".join(command)]
    else:
        argv = command

    environment = parse_environment(args.setenv)
    properties: dict[str, tuple[str, Any]] = {}
    unit_type = args.type
    description = args.description
    working_directory = args.working_directory
    tags = list(args.tags)
    slice_name = args.slice_name
    nice = args.nice
    runtime_max = args.runtime_max
    remain_after_exit = args.remain_after_exit
    collect = args.collect

    if profile is not None:
        inherited = profiles.resolve_environment(profile)
        environment = {**inherited, **environment}
        properties.update(profile.properties)
        unit_type = unit_type or profile.unit_type or "simple"
        description = description or profile.description
        working_directory = profiles.resolve_working_directory(profile)
        tags = list(dict.fromkeys((*profile.tags, *tags)))
        slice_name = slice_name or profile.slice_name
        nice = nice if nice is not None else profile.nice
        runtime_max = runtime_max if runtime_max is not None else profile.runtime_max_sec
        remain_after_exit = remain_after_exit or profile.remain_after_exit
        if collect is None:
            collect = profile.collect

    collect = profiles.choose_collect(collect, tags)

    properties.update(parse_property(item) for item in args.property)

    name = sd.normalize_unit_name(args.unit) if args.unit else sd.generate_unit_name(argv)
    spec = sd.TransientSpec(
        name=name,
        argv=argv,
        description=description,
        unit_type=unit_type,
        working_directory=working_directory or os.getcwd(),
        environment=environment,
        properties=properties,
        remain_after_exit=remain_after_exit,
        collect=collect,
        runtime_max_sec=runtime_max,
        nice=nice,
        slice_name=slice_name,
        tags=tags,
        session=args.session or session_id(),
        pin=args.wait,
    )

    try:
        if args.replace:
            job = await sd.replace_transient(bus, spec)
        else:
            job = await sd.start_transient(bus, spec, mode="fail")
    except DBusErrorResponse as error:
        if "Exists" in (error.name or ""):
            raise PystemctlError(
                f"unit {name} already exists; pass --replace to replace it"
            ) from error
        raise

    job_state = None if args.no_block else await sd.wait_job(bus, job)

    props = await sd.wait_until_finished(bus, name) if args.wait else await sd.try_unit_properties(bus, name)

    payload = {
        "unit": name,
        "job": job,
        "job_state": job_state,
        "profile": profile.name if profile else None,
        "active_state": props.get("ActiveState"),
        "sub_state": props.get("SubState"),
        "result": props.get("Result"),
        "main_status": props.get("ExecMainStatus"),
    }
    if not args.wait:
        emit(args, name, payload)

    if job_state is not None and job_state != "done":
        print(f"pystemctl: start job for {name} ended in state {job_state}", file=sys.stderr)
        return 1
    if not args.wait:
        return 0
    if args.json:
        emit(args, None, payload)
    if props.get("Result") == "exit-code":
        status = props.get("ExecMainStatus")
        return status if isinstance(status, int) and status else 1
    if props.get("Result") not in (None, "success"):
        return 1
    return 0
