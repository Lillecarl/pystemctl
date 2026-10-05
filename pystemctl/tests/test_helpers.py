from __future__ import annotations

import argparse
from collections.abc import AsyncIterator
from functools import partial
from typing import Any

import anyio
import pytest
from conftest import BUS

from pystemctl.bus import Scope
from pystemctl.cli import helpers
from pystemctl.errors import PystemctlError, UnitNotFoundError


def test_unit_session_reads_the_recorded_session() -> None:
    props = {"Environment": ["PATH=/run/x", "PYSTEMCTL_SESSION=abc123"]}
    assert helpers.unit_session(props) == "abc123"


def test_unit_session_is_none_without_a_record() -> None:
    assert helpers.unit_session({}) is None
    assert helpers.unit_session({"Environment": ["PATH=/run/x"]}) is None
    assert helpers.unit_session({"Environment": ["PYSTEMCTL_SESSION="]}) is None


def test_note_foreign_session_names_the_owner(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(helpers, "session_id", lambda: "mine")
    helpers.note_foreign_session("theirs.service", {"Environment": ["PYSTEMCTL_SESSION=theirs"]})
    assert "theirs.service belongs to session theirs" in capsys.readouterr().err


def test_note_foreign_session_stays_quiet_otherwise(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(helpers, "session_id", lambda: "mine")
    helpers.note_foreign_session("mine.service", {"Environment": ["PYSTEMCTL_SESSION=mine"]})
    helpers.note_foreign_session("plain.service", {})
    assert capsys.readouterr().err == ""


def _journal(monkeypatch: pytest.MonkeyPatch, entries: list[dict[str, Any]]) -> None:
    def open_reader(*, system_units: list[str], user_units: list[str]) -> object:
        return object()

    async def read(
        reader: object, *, tail: int, skip_notices: bool
    ) -> AsyncIterator[dict[str, Any]]:
        assert skip_notices is False
        for entry in entries:
            yield entry

    monkeypatch.setattr(helpers.jr, "open_reader", open_reader)
    monkeypatch.setattr(helpers.jr, "entries", read)


def test_has_journal_trace_finds_any_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _journal(monkeypatch, [{"MESSAGE": "Started x."}])
    assert anyio.run(helpers.has_journal_trace, "x.service", Scope.USER) is True


def test_has_journal_trace_empty_means_never_ran(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _journal(monkeypatch, [])
    assert anyio.run(helpers.has_journal_trace, "x.service", Scope.USER) is False


def _resolve_setup(monkeypatch: pytest.MonkeyPatch, props: dict[str, Any], trace: bool) -> None:
    async def target(bus: object, args: object) -> str:
        return "gone.service"

    async def properties(bus: object, name: str) -> dict[str, Any]:
        return props

    async def has_trace(name: str, scope: object) -> bool:
        return trace

    monkeypatch.setattr(helpers, "resolve_target", target)
    monkeypatch.setattr(helpers.sd, "try_unit_properties", properties)
    monkeypatch.setattr(helpers, "has_journal_trace", has_trace)


def test_resolve_existing_points_a_collected_unit_at_its_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _resolve_setup(monkeypatch, {"LoadState": "not-found"}, trace=True)
    with pytest.raises(PystemctlError, match="already finished and was collected"):
        anyio.run(helpers.resolve_existing, BUS, argparse.Namespace())


def test_resolve_existing_without_a_trace_is_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _resolve_setup(monkeypatch, {"LoadState": "not-found"}, trace=False)
    with pytest.raises(UnitNotFoundError, match="not found"):
        anyio.run(helpers.resolve_existing, BUS, argparse.Namespace())


def _watch_args(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {"grep": None, "json": False, "scope": Scope.USER}
    values.update(overrides)
    return argparse.Namespace(**values)


def _watch_lines(
    monkeypatch: pytest.MonkeyPatch,
    lines: list[str],
    seen: dict[str, object] | None = None,
    hang: bool = True,
) -> None:
    """Fake the journal stream; hanging afterwards models a running unit."""

    async def fake(**kwargs: object) -> AsyncIterator[str]:
        if seen is not None:
            seen.update(kwargs)
        for line in lines:
            yield line
        if hang:
            await anyio.sleep(30)

    monkeypatch.setattr(helpers.jr, "follow_lines", fake)


def _watch_finished(monkeypatch: pytest.MonkeyPatch, hang: bool = False) -> None:
    async def finished(bus: object, name: str) -> dict[str, object]:
        if hang:
            await anyio.sleep(30)
        return {"Result": "success", "ActiveState": "inactive", "ExecMainStatus": 0}

    monkeypatch.setattr(helpers.sd, "wait_until_finished", finished)


def test_watch_unit_finished_side_ends_the_stream(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _watch_lines(monkeypatch, ["hello"])
    _watch_finished(monkeypatch)
    outcome = helpers.WatchOutcome()
    watch = partial(
        helpers.watch_unit,
        BUS,
        "x.service",
        _watch_args(),
        outcome,
        replay=10,
        stop_on_match=False,
        skip_notices=True,
    )
    anyio.run(watch)
    assert capsys.readouterr().out == "hello\n"
    assert outcome.props["Result"] == "success"


def test_watch_unit_match_ends_the_finished_side(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _watch_lines(monkeypatch, ["READY"])
    _watch_finished(monkeypatch, hang=True)
    outcome = helpers.WatchOutcome()

    async def _main() -> None:
        with anyio.fail_after(5):
            await helpers.watch_unit(
                BUS,
                "x.service",
                _watch_args(grep="READY"),
                outcome,
                replay=10,
                stop_on_match=True,
                skip_notices=False,
            )

    anyio.run(_main)
    assert outcome.matched
    assert capsys.readouterr().out == "READY\n"


def test_watch_unit_forwards_replay_and_notice_flag(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, object] = {}
    _watch_lines(monkeypatch, ["hello"], seen)
    _watch_finished(monkeypatch)
    watch = partial(
        helpers.watch_unit,
        BUS,
        "x.service",
        _watch_args(grep="hello"),
        helpers.WatchOutcome(),
        replay=7,
        stop_on_match=True,
        skip_notices=False,
    )
    anyio.run(watch)
    assert seen["since_lines"] == 7
    assert seen["pattern"] == "hello"
    assert seen["skip_notices"] is False
    capsys.readouterr()


def test_watch_unit_without_finish_side_returns_when_the_stream_ends(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _watch_lines(monkeypatch, ["a", "b"], hang=False)
    outcome = helpers.WatchOutcome()
    watch = partial(
        helpers.watch_unit,
        BUS,
        "x.service",
        _watch_args(),
        outcome,
        replay=10,
        stop_on_match=True,
        skip_notices=True,
        watch_finish=False,
    )
    anyio.run(watch)
    assert capsys.readouterr().out.splitlines() == ["a", "b"]
    assert outcome.props == {}
