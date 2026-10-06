"""Shared test doubles.

BUS stands in for the D-Bus connection in tests that mock everything the
handler would call on it. It is typed so the checker holds and named so a
reader sees the lie; it must never be touched, or the test needs a fake
with behavior instead.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from anyio.abc import TaskGroup

from pystemctl.bus import Bus
from pystemctl.systemd.jobs import Job
from pystemctl.systemd.units import Unit

BUS = cast(Bus, None)


def as_task_group(double: object) -> TaskGroup:
    """Present a task-group test double where a group is required.

    The fakes only implement the cancel scope the watcher touches; the cast
    says so in one place instead of at every call site.
    """
    return cast(TaskGroup, double)


class FakeCancelScope:
    """Only cancel(); that is all the watcher touches."""

    def cancel(self) -> None:
        pass


class FakeTaskGroup:
    """A group double carrying a FakeCancelScope; present via as_task_group."""

    def __init__(self) -> None:
        self.cancel_scope = FakeCancelScope()


def make_unit(
    name: str = "job.service",
    active_state: str = "active",
    sub_state: str = "running",
) -> Unit:
    """A loaded, running unit; override only what the test reads."""
    return Unit(
        name=name,
        description="a job",
        load_state="loaded",
        active_state=active_state,
        sub_state=sub_state,
        following="",
        path="/org/freedesktop/systemd1/unit/job_2eservice",
        job_id=0,
        job_type="",
        job_path="",
    )


def make_job(
    name: str = "job.service",
    tags: Sequence[str] = (),
    session: str | None = None,
    active_state: str = "active",
    sub_state: str = "running",
    **props: object,
) -> Job:
    """A job double; extra keywords become its D-Bus properties."""
    return Job(
        unit=make_unit(name, active_state=active_state, sub_state=sub_state),
        tags=list(tags),
        session=session,
        environment={},
        props=dict(props),
    )
