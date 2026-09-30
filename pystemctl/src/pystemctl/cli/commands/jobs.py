"""List ephemeral jobs by the tags and session they carry."""

from __future__ import annotations

import argparse
import json

from ... import systemd as sd
from ...bus import Bus
from ...render import format_table
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
        print(
            json.dumps(
                [
                    {
                        **jsonable(unit_payload(job.unit)),
                        "tags": job.tags,
                        "session": job.session,
                    }
                    for job in jobs
                ]
            )
        )
        return 0

    if not jobs:
        return 1

    rows = [
        [
            job.name,
            job.unit.active_state,
            ",".join(job.tags) or "-",
            job.unit.description,
        ]
        for job in jobs
    ]
    print(format_table(["UNIT", "ACTIVE", "TAGS", "DESCRIPTION"], rows))
    return 0
