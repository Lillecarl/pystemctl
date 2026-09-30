"""Start an ephemeral unit from a command."""

from __future__ import annotations

import argparse
import os
import shutil
import sys

from jeepney.wrappers import DBusErrorResponse

from ... import systemd as sd
from ...bus import Bus
from ...errors import PystemctlError
from ..helpers import emit, parse_environment, parse_property, strip_separator


async def cmd_run(bus: Bus, args: argparse.Namespace) -> int:
    command = strip_separator(args.command)
    if not command:
        raise PystemctlError("no command given; use: pystemctl run [options] -- COMMAND [ARGS...]")

    if args.shell:
        argv = [shutil.which("sh") or "/bin/sh", "-c", " ".join(command)]
    else:
        argv = command

    name = sd.normalize_unit_name(args.unit) if args.unit else sd.generate_unit_name(argv)
    spec = sd.TransientSpec(
        name=name,
        argv=argv,
        description=args.description,
        unit_type=args.type,
        working_directory=args.working_directory or os.getcwd(),
        environment=parse_environment(args.setenv),
        properties=dict(parse_property(item) for item in args.property),
        remain_after_exit=args.remain_after_exit,
        collect=not args.no_collect,
        runtime_max_sec=args.runtime_max,
        nice=args.nice,
        slice_name=args.slice_name,
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
