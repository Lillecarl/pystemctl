"""List ephemeral jobs by the tags and session they carry."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections.abc import Awaitable, Callable

import anyio

from ... import systemd as sd
from ...bus import Bus
from ...render import LOCAL_TIMEZONE, format_duration, format_table
from ...systemd.jobs import Job
from ...systemd.tags import session_id
from ..helpers import jsonable, unit_payload

Snapshot = Callable[[], Awaitable[list[Job]]]

POLL_INTERVAL = 1.0


async def cmd_jobs(bus: Bus, args: argparse.Namespace) -> int:
    session = None if args.any_session else (args.session or session_id())

    async def snapshot(current: str | None) -> list[Job]:
        return await sd.collect_jobs(
            bus,
            required_tags=args.tags,
            session=current,
            include_inactive=args.all,
        )

    if args.follow:
        return await _follow(lambda: snapshot(session), args)

    jobs = await snapshot(session)
    if not jobs and session is not None:
        # A job started from another session — a shell, or an earlier agent
        # session — filters out of the scoped answer. Retry unscoped rather
        # than report nothing, the way resolve() already does when it targets
        # a unit by tag.
        jobs = await snapshot(None)

    if args.json:
        print(json.dumps([_job_payload(job) for job in jobs]))
        return 0

    if not jobs:
        return 1

    print(_table(jobs))
    return 0


async def _follow(snapshot: Snapshot, args: argparse.Namespace) -> int:
    """Emit a line per job added, changed, or removed, until interrupted.

    State is polled: a single PropertiesChanged match cannot cover every
    transient unit, and the AGE column implies a periodic refresh anyway.
    """
    seen: dict[str, dict[str, object]] = {}
    while True:
        jobs = {job.name: _job_payload(job) for job in await snapshot()}
        for name, payload in jobs.items():
            previous = seen.get(name)
            if previous is None:
                _emit_follow_line(args, "added", payload)
            elif _fingerprint(previous) != _fingerprint(payload):
                _emit_follow_line(args, "changed", payload)
        for name in seen.keys() - jobs.keys():
            _emit_follow_line(args, "removed", seen[name])
        seen = jobs
        await anyio.sleep(POLL_INTERVAL)


def _fingerprint(payload: dict[str, object]) -> tuple[object, ...]:
    # The fields that change while a job runs. An age tick alone is not a
    # change worth a line.
    return (
        payload.get("active"),
        payload.get("sub"),
        payload.get("result"),
        payload.get("exit_status"),
        payload.get("main_pid"),
    )


def _emit_follow_line(args: argparse.Namespace, event: str, payload: dict[str, object]) -> None:
    if args.json:
        print(json.dumps({"event": event, "job": jsonable(payload)}), flush=True)
        return
    status = payload.get("result") or payload.get("sub") or ""
    extra = f" {status}" if status else ""
    print(f"{event:<7} {payload.get('unit')}{extra}", flush=True)


def _table(jobs: list[Job]) -> str:
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
    return format_table(["UNIT", "ACTIVE", "STATUS", "AGE", "PID", "TAGS"], rows)


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
