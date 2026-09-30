"""Reading the journal through libsystemd.

The journal API is blocking, so every call into it runs in a worker thread.
The iteration is an async generator, which keeps cancellation working between
calls even though a single call cannot be interrupted.
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import AsyncIterator, Sequence
from typing import TYPE_CHECKING, Any

import anyio

from ..errors import PystemctlError

if TYPE_CHECKING:
    from systemd import journal


def _journal_module() -> Any:
    try:
        from systemd import journal
    except ImportError as error:
        raise PystemctlError(
            "python-systemd is required for journal access but is not installed"
        ) from error
    return journal


def unit_match_groups(
    *,
    system_units: Sequence[str] = (),
    user_units: Sequence[str] = (),
    uid: str | None = None,
) -> list[list[tuple[str, str]]]:
    """Build the field groups journalctl uses to select a unit's entries.

    Each inner list is a conjunction; the groups are ORed together. Two matches
    on the same field are ORed by the journal, which the user-unit daemon group
    relies on. Selection needs the groups because the manager's own messages
    carry ``USER_UNIT=``/``UNIT=`` rather than ``_SYSTEMD_USER_UNIT=``.
    """
    uid = uid if uid is not None else str(os.getuid())
    groups: list[list[tuple[str, str]]] = []
    for unit in system_units:
        groups.append([("_SYSTEMD_UNIT", unit)])
        groups.append([("_SYSTEMD_CGROUP", "/init.scope"), ("UNIT", unit)])
        groups.append([("_UID", "0"), ("OBJECT_SYSTEMD_UNIT", unit)])
    for unit in user_units:
        groups.append([("_SYSTEMD_USER_UNIT", unit), ("_UID", uid)])
        groups.append([("USER_UNIT", unit), ("_UID", uid)])
        groups.append([("OBJECT_SYSTEMD_USER_UNIT", unit), ("_UID", uid), ("_UID", "0")])
    return groups


def open_reader(
    *,
    system_units: Sequence[str] = (),
    user_units: Sequence[str] = (),
    priority: int | None = None,
    boot: str | bool | None = None,
) -> "journal.Reader":
    journal = _journal_module()
    reader = journal.Reader(flags=journal.LOCAL_ONLY)
    if priority is not None:
        reader.log_level(priority)
    if boot is not None:
        reader.this_boot(None if boot is True else boot)
    groups = unit_match_groups(system_units=system_units, user_units=user_units)
    for index, group in enumerate(groups):
        if index:
            reader.add_disjunction()
        for field, value in group:
            reader.add_match(f"{field}={value}")
    return reader


async def entries(
    reader: "journal.Reader",
    *,
    since: dt.datetime | None = None,
    until: dt.datetime | None = None,
    tail: int | None = None,
    follow: bool = False,
) -> AsyncIterator[dict[str, Any]]:
    if tail is not None:
        await anyio.to_thread.run_sync(reader.seek_tail)
        buffered: list[dict[str, Any]] = []
        for _ in range(tail):
            entry = await anyio.to_thread.run_sync(reader.get_previous)
            if not entry:
                break
            buffered.append(entry)
        for entry in reversed(buffered):
            if until is not None and entry["__REALTIME_TIMESTAMP"] > until:
                continue
            yield entry
    else:
        if since is not None:
            await anyio.to_thread.run_sync(reader.seek_realtime, since)
        else:
            await anyio.to_thread.run_sync(reader.seek_head)
        while True:
            entry = await anyio.to_thread.run_sync(reader.get_next)
            if not entry:
                break
            if until is not None and entry["__REALTIME_TIMESTAMP"] > until:
                return
            yield entry
        if not follow:
            return

    if not follow:
        return

    await anyio.to_thread.run_sync(reader.seek_tail)
    await anyio.to_thread.run_sync(reader.get_previous)
    journal = _journal_module()
    while True:
        changed = await anyio.to_thread.run_sync(reader.wait, 1.0)
        if changed != journal.APPEND:
            continue
        while True:
            entry = await anyio.to_thread.run_sync(reader.get_next)
            if not entry:
                break
            yield entry
