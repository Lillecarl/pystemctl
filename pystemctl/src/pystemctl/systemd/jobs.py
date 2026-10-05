"""Querying ephemeral jobs by the tags they carry."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from jeepney.wrappers import DBusErrorResponse

from ..bus import UNIT_INTERFACE, Bus
from ..errors import PystemctlError
from .tags import read_tags, session_id
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

    @property
    def started_at(self) -> int:
        """Microseconds since the epoch when the job started, or 0."""
        for key in ("ActiveEnterTimestamp", "ExecMainStartTimestamp", "StateChangeTimestamp"):
            value = self.props.get(key)
            if isinstance(value, int):
                return value
        return 0

    @property
    def main_pid(self) -> int:
        value = self.props.get("MainPID")
        return value if isinstance(value, int) else 0

    @property
    def result(self) -> str | None:
        """The outcome once the job has stopped, or None while it runs."""
        if self.unit.active_state in {"inactive", "failed"}:
            value = self.props.get("Result")
            return value if isinstance(value, str) else None
        return None

    @property
    def exit_status(self) -> int | None:
        if self.result == "exit-code":
            value = self.props.get("ExecMainStatus")
            return value if isinstance(value, int) else None
        return None


async def collect_jobs(
    bus: Bus,
    *,
    required_tags: Sequence[str] = (),
    session: str | None = None,
    include_inactive: bool = False,
) -> list[Job]:
    """Return the transient units matching the tag and session filters.

    ``ListUnits`` cannot filter by anything but name and state, so a
    candidate's properties are read and the filters applied locally. Only
    transient units are considered: a job is a unit pystemctl created.

    Candidates are narrowed by name first. A busy session lists hundreds of
    units, nearly all of them devices and mounts, and reading each one to
    discover it is not transient made a scan take seconds.
    """
    jobs: list[Job] = []
    for unit in await list_units(bus):
        if not include_inactive and not unit.is_active:
            continue
        if not _could_be_transient(unit.name):
            continue
        job = await _job_for_unit(bus, unit, session=session, required_tags=required_tags)
        if job is not None:
            jobs.append(job)
    jobs.sort(key=lambda job: job.name)
    return jobs


def _could_be_transient(name: str) -> bool:
    """Whether a unit of this name could be a job, before reading it.

    Every unit systemd can start transiently is a service or a scope; the
    other suffixes are devices, mounts and slices, which a session has
    hundreds of. Testing the name avoids reading each one to find that out.
    """
    return name.endswith((".service", ".scope"))


async def _job_for_unit(
    bus: Bus,
    unit: Unit,
    *,
    session: str | None,
    required_tags: Sequence[str],
) -> Job | None:
    """Build a Job for one unit, or None if it is not a matching job.

    A unit can be collected between ListUnits and this read, so its path stops
    answering. That is a job that went away, not an error: it returns None.
    """
    try:
        props = await bus.get_all(unit.path, UNIT_INTERFACE)
        if not props.get("Transient"):
            return None
        # Environment lives on the unit-type interface (.service), not Unit.
        interface = unit_interface(unit.name)
        if interface is not None:
            props.update(await bus.get_all(unit.path, interface))
    except DBusErrorResponse:
        return None
    environment = environment_of(props)
    tags, unit_session = read_tags(environment)
    if session is not None and unit_session != session:
        return None
    if any(tag not in tags for tag in required_tags):
        return None
    return Job(
        unit=unit,
        tags=tags,
        session=unit_session,
        environment=environment,
        props=props,
    )


def _started_at(job: Job) -> int:
    return job.started_at


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
