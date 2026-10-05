from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import anyio
import pytest

from pystemctl.bus import Scope
from pystemctl.cli import helpers
from pystemctl.errors import PystemctlError


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
    helpers.note_foreign_session(
        "theirs.service", {"Environment": ["PYSTEMCTL_SESSION=theirs"]}
    )
    assert "theirs.service belongs to session theirs" in capsys.readouterr().err


def test_note_foreign_session_stays_quiet_otherwise(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(helpers, "session_id", lambda: "mine")
    helpers.note_foreign_session(
        "mine.service", {"Environment": ["PYSTEMCTL_SESSION=mine"]}
    )
    helpers.note_foreign_session("plain.service", {})
    assert capsys.readouterr().err == ""


def _journal(monkeypatch: pytest.MonkeyPatch, entries: list[dict[str, Any]]) -> None:
    def open_reader(
        *, system_units: list[str], user_units: list[str]
    ) -> object:
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


def _resolve_setup(
    monkeypatch: pytest.MonkeyPatch, props: dict[str, Any], trace: bool
) -> None:
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
        anyio.run(helpers.resolve_existing, None, object())


def test_resolve_existing_without_a_trace_is_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _resolve_setup(monkeypatch, {"LoadState": "not-found"}, trace=False)
    with pytest.raises(PystemctlError, match="not found"):
        anyio.run(helpers.resolve_existing, None, object())
