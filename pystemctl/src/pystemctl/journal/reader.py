"""Reading the journal through libsystemd.

The journal API is blocking, so every call into it runs in a worker thread.
The iteration is an async generator, which keeps cancellation working between
calls even though a single call cannot be interrupted.
"""

from __future__ import annotations

import datetime as dt
import os
import re
from collections.abc import AsyncIterator, Sequence
from typing import TYPE_CHECKING, Any

import anyio

from ..errors import PystemctlError
from ..systemd.tags import TAG_FIELD

if TYPE_CHECKING:
    from systemd import journal

# sd_journal_wait returns one of these; the values are the ABI's, not a
# choice. Imported as constants so following reads them without pulling in
# libsystemd on every wake, and so the reader works without it installed.
_APPEND = 1
_INVALIDATE = 2


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
    tags: Sequence[str] = (),
    uid: str | None = None,
    priority: int | None = None,
    boot: str | bool | None = None,
) -> journal.Reader:
    journal = _journal_module()
    reader = journal.Reader(flags=journal.LOCAL_ONLY)
    if priority is not None:
        reader.log_level(priority)
    if boot is not None:
        reader.this_boot(None if boot is True else boot)
    groups = unit_match_groups(system_units=system_units, user_units=user_units, uid=uid)
    if tags:
        groups.append([(TAG_FIELD, tag) for tag in tags])
    for index, group in enumerate(groups):
        if index:
            reader.add_disjunction()
        for field, value in group:
            reader.add_match(f"{field}={value}")
    return reader


async def newest_unit_for_tags(
    tags: Sequence[str], *, system: bool = False, scan: int = 1000
) -> str | None:
    """Name of the unit that most recently logged under every given tag.

    A finished transient unit is unloaded, so the bus cannot resolve it; its
    journal entries outlive it. Each entry carries one PYSTEMCTL_TAG field per
    tag, and entries in one conjunction group must carry every tag.

    The unit comes from the notice's subject, not its sender: the manager
    logs from its own scope, naming the job in USER_UNIT (user) or UNIT
    (system). The service's own lines name it in _SYSTEMD_USER_UNIT instead.
    """
    cleaned = [tag for tag in tags if tag]
    if not cleaned:
        return None
    reader = open_reader(tags=cleaned)
    found: str | None = None
    async for entry in entries(reader, tail=scan):
        if system:
            name = entry.get("UNIT") or entry.get("_SYSTEMD_UNIT")
        else:
            name = entry.get("USER_UNIT") or entry.get("_SYSTEMD_USER_UNIT")
        if name:
            found = str(name)
    return found


async def entries(
    reader: journal.Reader,
    *,
    since: dt.datetime | None = None,
    until: dt.datetime | None = None,
    tail: int | None = None,
    follow: bool = False,
    skip_notices: bool = False,
) -> AsyncIterator[dict[str, Any]]:
    # The cursor of the last entry read, so following can resume exactly where
    # the replay stopped. Seeking to the tail again would drop every entry
    # written between the replay and the follow attaching.
    cursor: str | None = None

    if tail is not None:
        await anyio.to_thread.run_sync(reader.seek_tail)
        buffered: list[dict[str, Any]] = []
        while len(buffered) < tail:
            entry = await anyio.to_thread.run_sync(reader.get_previous)
            if not entry:
                break
            # The scan runs newest-first, so entries past the bound come
            # first: skip them without counting, then collect the last N at
            # or before it. Filtering after the tail instead would keep the
            # newest N and drop whatever falls past the bound -- usually all
            # of them -- instead of the N the bound actually covers.
            if until is not None and entry["__REALTIME_TIMESTAMP"] > until:
                continue
            if skip_notices and is_manager_notice(entry):
                continue
            buffered.append(entry)
        for entry in reversed(buffered):
            cursor = entry.get("__CURSOR", cursor)
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
            cursor = entry.get("__CURSOR", cursor)
            if until is not None and entry["__REALTIME_TIMESTAMP"] > until:
                return
            if skip_notices and is_manager_notice(entry):
                continue
            yield entry
        if not follow:
            return

    if not follow:
        return

    if cursor is not None:
        # seek_cursor positions before the entry, so get_next returns the one
        # just replayed; skip it before reading what follows.
        await anyio.to_thread.run_sync(reader.seek_cursor, cursor)
        await anyio.to_thread.run_sync(reader.get_next)
    else:
        await anyio.to_thread.run_sync(reader.seek_tail)
        await anyio.to_thread.run_sync(reader.get_previous)
    while True:
        changed = await anyio.to_thread.run_sync(reader.wait, 1.0)
        if changed != _APPEND:
            continue
        while True:
            entry = await anyio.to_thread.run_sync(reader.get_next)
            if not entry:
                break
            if skip_notices and is_manager_notice(entry):
                continue
            yield entry


_NOTICE_PATTERN = re.compile(
    r"^(Starting|Started|Stopping|Stopped|Finished|Reloading|Reloaded)\b"
    r"|: Consumed .* CPU time"
    r"|^Main processes terminated with"
)


def is_manager_notice(entry: dict[str, Any]) -> bool:
    """Whether the entry is the manager narrating a unit's lifecycle.

    Started/stopped/finished lines and resource accounting come from PID 1
    under the systemd identifier. A unit's own output never carries that
    identifier unless it deliberately sets it, so gating on both keeps real
    output safe. pystemctl shows the program's output; pyjournalctl shows
    everything.
    """
    if entry.get("SYSLOG_IDENTIFIER") != "systemd":
        return False
    message = entry.get("MESSAGE")
    if isinstance(message, bytes):
        text = message.decode("utf-8", "replace")
    elif message is None:
        return False
    else:
        text = str(message)
    return _NOTICE_PATTERN.search(text) is not None
