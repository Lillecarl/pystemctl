"""List ephemeral jobs by the tags and session they carry."""

from __future__ import annotations

import argparse
import datetime as dt
import json

from ... import systemd as sd
from ...bus import Bus
from ...render import LOCAL_TIMEZONE, format_duration, format_table
from ...systemd.jobs import Job
from ...systemd.tags import session_id
from ..helpers import jsonable, unit_payload


async def cmd_jobs(bus: Bus, args: argparse.Namespace) -> int:
    session = None if args.any_session else (args.session or session_id())
    jobs = await sd.collect_jobs(
        bus,
        required_tags=args.tags,
        session=session,
        include_inactive=args.all,
    )

    if args.json:
        print(json.dumps([_job_payload(job) for job in jobs]))
        return 0

    if not jobs:
        return 1

    rows = [
        [
            job.name,
            job.unit.active_state,
            _status_cell(job),
            _age_cell(job),
            str(job.main_pid or "-"),
            ",".join(job.tags) or "-",
        ]
        for job in jobs
    ]
    print(format_table(["UNIT", "ACTIVE", "STATUS", "AGE", "PID", "TAGS"], rows))
    return 0


def _job_payload(job: Job) -> dict[str, object]:
    return {
        **jsonable(unit_payload(job.unit)),
        "tags": job.tags,
        "session": job.session,
        "main_pid": job.main_pid,
        "started_at": job.started_at,
        "result": job.result,
        "exit_status": job.exit_status,
    }


def _status_cell(job: Job) -> str:
    result = job.result
    if result is None:
        return job.unit.sub_state
    status = job.exit_status
    return f"{result} ({status})" if status is not None else result


def _age_cell(job: Job) -> str:
    started = job.started_at
    if not started:
        return "-"
    when = dt.datetime.fromtimestamp(started / 1_000_000, tz=LOCAL_TIMEZONE)
    return format_duration(dt.datetime.now(tz=LOCAL_TIMEZONE) - when)
