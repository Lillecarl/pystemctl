from __future__ import annotations

from types import SimpleNamespace

from pystemctl.systemd.jobs import _started_at


def _job(**props: object) -> object:
    return SimpleNamespace(props=props)


def test_started_at_prefers_active_enter() -> None:
    job = _job(ActiveEnterTimestamp=100, ExecMainStartTimestamp=50, StateChangeTimestamp=10)
    assert _started_at(job) == 100


def test_started_at_falls_back_through_properties() -> None:
    assert _started_at(_job(StateChangeTimestamp=7)) == 7
    assert _started_at(_job(ExecMainStartTimestamp=9)) == 9


def test_started_at_ignores_missing_and_non_int() -> None:
    assert _started_at(_job()) == 0
    assert _started_at(_job(ActiveEnterTimestamp=None, StateChangeTimestamp="x")) == 0
