from __future__ import annotations

import datetime as dt

import pytest

from pystemctl.errors import PystemctlError
from pystemctl.journal import parse_timestamp, priority_value, unit_match_groups


@pytest.fixture
def now() -> dt.datetime:
    return dt.datetime(2026, 9, 30, 12, 0, 0, tzinfo=dt.timezone.utc)


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
