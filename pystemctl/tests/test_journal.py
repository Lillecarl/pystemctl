from __future__ import annotations

import datetime as dt
from functools import partial
from typing import Any

import anyio
import pytest

from pystemctl.errors import PystemctlError
from pystemctl.journal import parse_timestamp, priority_value, unit_match_groups
from pystemctl.journal.reader import entries, is_manager_notice, message_text


@pytest.fixture
def now() -> dt.datetime:
    return dt.datetime(2026, 9, 30, 12, 0, 0, tzinfo=dt.UTC)


def test_now(now: dt.datetime) -> None:
    assert parse_timestamp("now", now=now) == now


def test_iso_naive_gets_local_timezone(now: dt.datetime) -> None:
    parsed = parse_timestamp("2026-01-02T03:04:05", now=now)
    assert parsed.year == 2026
    assert parsed.tzinfo is not None


def test_epoch(now: dt.datetime) -> None:
    assert parse_timestamp("@0", now=now).timestamp() == 0


def test_relative_ago(now: dt.datetime) -> None:
    assert parse_timestamp("2 hours ago", now=now) == now - dt.timedelta(hours=2)


def test_relative_bare_is_past(now: dt.datetime) -> None:
    assert parse_timestamp("3d", now=now) == now - dt.timedelta(days=3)


def test_relative_plus_is_future(now: dt.datetime) -> None:
    assert parse_timestamp("+1h", now=now) == now + dt.timedelta(hours=1)


def test_bad_timestamp_raises(now: dt.datetime) -> None:
    with pytest.raises(PystemctlError):
        parse_timestamp("not a time", now=now)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("err", 3), ("debug", 7), ("0", 0), ("7", 7)],
)
def test_priority_value(text: str, expected: int) -> None:
    assert priority_value(text) == expected


def test_priority_out_of_range() -> None:
    with pytest.raises(PystemctlError):
        priority_value("9")


def test_user_unit_match_groups() -> None:
    assert unit_match_groups(user_units=["foo.service"], uid="1000") == [
        [("_SYSTEMD_USER_UNIT", "foo.service"), ("_UID", "1000")],
        [("USER_UNIT", "foo.service"), ("_UID", "1000")],
        [("OBJECT_SYSTEMD_USER_UNIT", "foo.service"), ("_UID", "1000"), ("_UID", "0")],
    ]


def test_system_unit_match_groups() -> None:
    assert unit_match_groups(system_units=["bar.service"], uid="1000") == [
        [("_SYSTEMD_UNIT", "bar.service")],
        [("_SYSTEMD_CGROUP", "/init.scope"), ("UNIT", "bar.service")],
        [("_UID", "0"), ("OBJECT_SYSTEMD_UNIT", "bar.service")],
    ]


@pytest.mark.parametrize(
    "message",
    [
        "Started job.service.",
        "Starting mbsync mailbox synchronization...",
        "Stopped job.service.",
        "Finished mbsync mailbox synchronization.",
        "Reloaded job.service.",
        "job.service: Consumed 17.443s CPU time over 2min wall clock time.",
        "Main processes terminated with: code=exited, status=0/SUCCESS",
    ],
)
def test_manager_lifecycle_lines_are_notices(message: str) -> None:
    assert is_manager_notice({"SYSLOG_IDENTIFIER": "systemd", "MESSAGE": message})


def test_bytes_messages_are_notices_too() -> None:
    assert is_manager_notice({"SYSLOG_IDENTIFIER": "systemd", "MESSAGE": b"Started job.service."})


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        ({"MESSAGE": "plain"}, "plain"),
        ({"MESSAGE": b"bytes"}, "bytes"),
        ({"MESSAGE": None}, ""),
        ({}, ""),
        ({"MESSAGE": 42}, "42"),
    ],
)
def test_message_text_decodes_every_shape(entry: dict[str, object], expected: str) -> None:
    assert message_text(entry) == expected


@pytest.mark.parametrize(
    "entry",
    [
        {"SYSLOG_IDENTIFIER": "echo", "MESSAGE": "Started the day well"},
        {"SYSLOG_IDENTIFIER": "systemd", "MESSAGE": "all systems nominal"},
        {"MESSAGE": "Started job.service."},
        {"SYSLOG_IDENTIFIER": "systemd"},
    ],
)
def test_output_lines_are_not_notices(entry: dict[str, object]) -> None:
    assert not is_manager_notice(entry)


class _TailedReader:
    """A fixed log read backwards, like seek_tail plus get_previous."""

    def __init__(self, log: list[dict[str, Any]]) -> None:
        self.log = log

    def seek_tail(self) -> None:
        pass

    def get_previous(self) -> dict[str, Any] | None:
        return self.log.pop() if self.log else None


async def _collect(reader: _TailedReader, **kwargs: Any) -> list[str]:
    return [str(entry["MESSAGE"]) async for entry in entries(reader, tail=10, **kwargs)]


def test_tailed_entries_skip_notices_on_request() -> None:
    log: list[dict[str, Any]] = [
        {"SYSLOG_IDENTIFIER": "systemd", "MESSAGE": "Started job.service."},
        {"SYSLOG_IDENTIFIER": "echo", "MESSAGE": "hello"},
        {"SYSLOG_IDENTIFIER": "systemd", "MESSAGE": "Stopped job.service."},
    ]
    assert anyio.run(partial(_collect, _TailedReader(list(log)))) == [
        "Started job.service.",
        "hello",
        "Stopped job.service.",
    ]
    assert anyio.run(partial(_collect, _TailedReader(list(log)), skip_notices=True)) == ["hello"]


def test_tail_with_until_reads_back_from_the_bound() -> None:
    """-n N --until T is the last N lines at or before T, not the last N."""
    base = dt.datetime(2026, 9, 30, 12, 0, 0, tzinfo=dt.UTC)
    log: list[dict[str, Any]] = [
        {"MESSAGE": f"line{i}", "__REALTIME_TIMESTAMP": base + dt.timedelta(minutes=i)}
        for i in range(5)
    ]

    async def _tail(tail: int, until: dt.datetime) -> list[str]:
        return [
            str(entry["MESSAGE"])
            async for entry in entries(_TailedReader(list(log)), tail=tail, until=until)
        ]

    bound = base + dt.timedelta(minutes=2)
    assert anyio.run(partial(_tail, 2, bound)) == ["line1", "line2"]
    # The old shape collected the newest two and dropped both past the
    # bound, printing nothing; the bound now scopes the collection.
    assert anyio.run(partial(_tail, 10, bound)) == ["line0", "line1", "line2"]
