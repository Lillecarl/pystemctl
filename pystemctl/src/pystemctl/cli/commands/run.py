"""Start an ephemeral unit from a command."""

from __future__ import annotations

import os
import shlex
import shutil
import sys
from typing import Any

from jeepney.wrappers import DBusErrorResponse

from ... import profiles
from ... import systemd as sd
from ...bus import Bus
from ...errors import PystemctlError
from ...systemd.tags import RESERVED, session_id
from ..args import RunArgs, WatchArgs
from ..helpers import (
    WatchOutcome,
    emit,
    parse_environment,
    parse_property,
    strip_separator,
    watch_unit,
)
from ..output import warn


def _caller_environment(args: RunArgs) -> dict[str, str]:
    """The invoking process's environment, unless --clean was passed.

    Reserved tag variables never ride along: they name the job for the
    lookup commands, and an inherited value would spoof them.
    """
    if args.clean:
        return {}
    return {key: value for key, value in os.environ.items() if key not in RESERVED}


def _load_profile(args: RunArgs) -> profiles.Profile | None:
    if not args.profile:
        return None
    available = profiles.load_profiles()
    if args.profile not in available:
        names = ", ".join(sorted(available)) or "none defined"
        raise PystemctlError(f"profile {args.profile!r} not found (available: {names})")
    return profiles.apply_cli_overrides(available[args.profile], args)


async def cmd_run(bus: Bus, args: RunArgs) -> int:
    command = strip_separator(args.command)
    if not command:
        raise PystemctlError("no command given; use: pystemctl run [options] -- COMMAND [ARGS...]")

    profile = _load_profile(args)

    if args.shell:
        argv = [shutil.which("sh") or "/bin/sh", "-c", shlex.join(command)]
    else:
        argv = command

    explicit = parse_environment(args.setenv)
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

    if profile is None:
        # No profile: the job runs as the caller would, with the caller's
        # environment. Explicit --setenv wins over inherited values.
        environment = {**_caller_environment(args), **explicit}
    else:
        inherited = profiles.resolve_environment(profile)
        environment = {**inherited, **explicit}
        properties.update(profile.properties)
        unit_type = unit_type or profile.unit_type
        description = description or profile.description
        working_directory = profiles.resolve_working_directory(profile)
        tags = list(dict.fromkeys((*profile.tags, *tags)))
        slice_name = slice_name or profile.slice_name
        nice = nice if nice is not None else profile.nice
        runtime_max = runtime_max if runtime_max is not None else profile.runtime_max_sec
        remain_after_exit = remain_after_exit or profile.remain_after_exit
        unit_type = unit_type or profile.unit_type
        if collect is None:
            collect = profile.collect

    # Explicit --type wins, then the profile, then the service default.
    unit_type = unit_type or "simple"
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

    if args.wait and not args.json:
        # Text mode shows the output as it happens; the unit name still comes
        # at the end, but on stderr, so stdout holds only the command's own
        # output and stays safe to capture or pipe.
        outcome = WatchOutcome()
        # run never watches for a pattern; the watcher gets a pattern-less view.
        view = WatchArgs(scope=args.scope, json=args.json)
        await watch_unit(
            bus, name, view, outcome, replay=100, stop_on_match=False, skip_notices=True
        )
        props = outcome.props
    else:
        props = (
            await sd.wait_until_finished(bus, name)
            if args.wait
            else await sd.try_unit_properties(bus, name)
        )

    payload = {
        "unit": name,
        "job": job,
        "job_state": job_state,
        "profile": profile.name if profile else None,
        "active_state": props.get("ActiveState"),
        "sub_state": props.get("SubState"),
        "result": props.get("Result"),
        "exit_status": props.get("ExecMainStatus"),
    }
    if not args.wait:
        emit(args, name, payload)

    if job_state is not None and job_state != "done":
        warn(f"start job for {name} ended in state {job_state}")
        return 1
    if not args.wait:
        if not args.json:
            warn(f"see it with pystemctl logs {name}, or pystemctl wait {name}")
        return 0
    if args.json:
        emit(args, name, payload)
    else:
        print(name, file=sys.stderr)
    if props.get("Result") == "exit-code":
        status = props.get("ExecMainStatus")
        return status if isinstance(status, int) and status else 1
    if props.get("Result") not in (None, "success"):
        return 1
    return 0
