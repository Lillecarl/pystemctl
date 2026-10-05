"""Shared test doubles.

BUS stands in for the D-Bus connection in tests that mock everything the
handler would call on it. It is typed so the checker holds and named so a
reader sees the lie; it must never be touched, or the test needs a fake
with behavior instead.
"""

from __future__ import annotations

from typing import cast

from anyio.abc import TaskGroup

from pystemctl.bus import Bus

BUS = cast(Bus, None)


def as_task_group(double: object) -> TaskGroup:
    """Present a task-group test double where a group is required.

    The fakes only implement the cancel scope the watcher touches; the cast
    says so in one place instead of at every call site.
    """
    return cast(TaskGroup, double)
