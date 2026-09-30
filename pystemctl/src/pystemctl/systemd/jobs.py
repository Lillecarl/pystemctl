"""Querying ephemeral jobs by the tags they carry."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from ..bus import UNIT_INTERFACE, Bus
from ..errors import PystemctlError
from .tags import session_id, read_tags
from .units import Unit, environment_of, list_units, unit_interface


@dataclass(slots=True)
class Job:
    """An ephemeral unit plus the metadata stripped from its environment."""

    unit: Unit
    tags: list[str]
    session: str | None
    environment: dict[str, str]
    props: dict[str, Any]

    @property
    def name(self) -> str:
        return self.unit.name


async def collect_jobs(
    bus: Bus,
    *,
    required_tags: Sequence[str] = (),
    session: str | None = None,
    include_inactive: bool = False,
) -> list[Job]:
    """Return the transient units matching the tag and session filters.

    ``ListUnits`` cannot filter by anything but name and state, so every
    candidate unit's properties are read and the filters applied locally. Only
    transient units are considered: a job is a unit pystemctl created.
    """
    jobs: list[Job] = []
    for unit in await list_units(bus):
        if not include_inactive and not unit.is_active:
            continue
        props = await bus.get_all(unit.path, UNIT_INTERFACE)
        if not props.get("Transient"):
            continue
        # Environment lives on the unit-type interface (.service), not on Unit.
        interface = unit_interface(unit.name)
        if interface is not None:
            props.update(await bus.get_all(unit.path, interface))
        environment = environment_of(props)
        tags, unit_session = read_tags(environment)
        if session is not None and unit_session != session:
            continue
        if any(tag not in tags for tag in required_tags):
            continue
        jobs.append(Job(unit=unit, tags=tags, session=unit_session, environment=environment, props=props))
    jobs.sort(key=lambda job: job.name)
    return jobs


def _started_at(job: Job) -> int:
    for key in ("ActiveEnterTimestamp", "ExecMainStartTimestamp", "StateChangeTimestamp"):
        value = job.props.get(key)
        if isinstance(value, int):
            return value
    return 0


async def resolve(
    bus: Bus,
    *,
    unit: str | None = None,
    tags: Sequence[str] = (),
    session: str | None = None,
    include_inactive: bool = True,
) -> tuple[Job | None, list[Job]]:
    """Turn a unit name or a set of tags into one job.

    A unit name is taken as given. Tags are a filter: the most recently
    started match wins, because tags are not unique and the usual case is a
    tag reused across a series of jobs. The caller decides what to do about
    the other matches.
    """
    if unit is not None:
        return None, []
    if not tags:
        raise PystemctlError("give a unit name or at least one --tag")

    jobs = await collect_jobs(
        bus,
        required_tags=tags,
        session=session if session is not None else session_id(),
        include_inactive=include_inactive,
    )
    if not jobs:
        # Retry without the session filter so a job from another session at
        # least reports as found-but-not-mine rather than not found.
        jobs = await collect_jobs(
            bus, required_tags=tags, session=None, include_inactive=include_inactive
        )
    if not jobs:
        raise PystemctlError(f"no job tagged {', '.join(tags)}")

    jobs.sort(key=_started_at, reverse=True)
    return jobs[0], jobs[1:]
