from __future__ import annotations

import argparse
from typing import Any

import anyio
import pytest
from jeepney.wrappers import DBusErrorResponse

from pystemctl.cli import helpers
from pystemctl.cli.commands import control as control_cmd


def _bus_error(name: str, data: object) -> DBusErrorResponse:
    # DBusErrorResponse builds itself from a wire message, which a unit test
    # does not have; only its name and payload matter here.
    error = DBusErrorResponse.__new__(DBusErrorResponse)
    error.name = name
    error.data = data
    return error


def _properties(monkeypatch: pytest.MonkeyPatch, props: dict[str, Any]) -> None:
    async def fake(bus: object, name: str) -> dict[str, Any]:
        return props

    monkeypatch.setattr(control_cmd.sd, "try_unit_properties", fake)


def test_unit_action_names_a_missing_unit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """stop on an unknown unit reads as not-found, not raw D-Bus."""

    async def fail(bus: object, name: str) -> str:
        raise _bus_error(
            "org.freedesktop.systemd1.NoSuchUnit", ("Unit x.service not loaded.",)
        )

    _properties(monkeypatch, {})
    args = argparse.Namespace(units=["x"], json=False)
    code = anyio.run(control_cmd._unit_action, None, args, fail)
    assert code == 1
    err = capsys.readouterr().err
    assert "Unit x.service not found." in err
    assert "NoSuchUnit" not in err


def test_unit_action_keeps_other_errors_verbatim(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def fail(bus: object, name: str) -> str:
        raise _bus_error("org.freedesktop.systemd1.Failure", ("boom",))

    _properties(monkeypatch, {})
    args = argparse.Namespace(units=["x"], json=False)
    code = anyio.run(control_cmd._unit_action, None, args, fail)
    assert code == 1
    assert "boom" in capsys.readouterr().err


def test_rm_reports_a_unit_that_was_never_there(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _properties(monkeypatch, {})
    monkeypatch.setattr(control_cmd, "has_journal_trace", _trace(False))
    args = argparse.Namespace(units=["ghost"], json=False)
    code = anyio.run(control_cmd.cmd_rm, None, args)
    assert code == 1
    captured = capsys.readouterr()
    assert "not found" in captured.err
    assert "Removed" not in captured.out


def _trace(found: bool) -> Any:
    async def fake(name: str, scope: object) -> bool:
        return found

    return fake


def test_rm_forgives_a_unit_that_is_already_gone(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Forgetting what is already forgotten is done, not an error.
    _properties(monkeypatch, {})
    monkeypatch.setattr(control_cmd, "has_journal_trace", _trace(True))
    args = argparse.Namespace(units=["old.service"], json=False)
    code = anyio.run(control_cmd.cmd_rm, None, args)
    assert code == 0
    captured = capsys.readouterr()
    assert "already finished and was collected" in captured.out
    assert "Removed" not in captured.out


def test_stop_warns_about_another_sessions_unit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def stop(bus: object, name: str) -> str:
        return "job"

    async def waited(bus: object, job: str) -> str:
        return "done"

    _properties(
        monkeypatch,
        {
            "LoadState": "loaded",
            "ActiveState": "active",
            "Environment": ["PYSTEMCTL_SESSION=someone-else"],
        },
    )
    monkeypatch.setattr(helpers, "session_id", lambda: "mine")
    monkeypatch.setattr(control_cmd.sd, "wait_job", waited)
    args = argparse.Namespace(units=["theirs.service"], json=False)
    code = anyio.run(control_cmd._unit_action, None, args, stop)
    assert code == 0
    err = capsys.readouterr().err
    assert "theirs.service belongs to session someone-else" in err


def test_stop_stays_quiet_for_its_own_session(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def stop(bus: object, name: str) -> str:
        return "job"

    async def waited(bus: object, job: str) -> str:
        return "done"

    _properties(
        monkeypatch,
        {
            "LoadState": "loaded",
            "ActiveState": "active",
            "Environment": ["PYSTEMCTL_SESSION=mine"],
        },
    )
    monkeypatch.setattr(helpers, "session_id", lambda: "mine")
    monkeypatch.setattr(control_cmd.sd, "wait_job", waited)
    args = argparse.Namespace(units=["mine.service"], json=False)
    code = anyio.run(control_cmd._unit_action, None, args, stop)
    assert code == 0
    assert capsys.readouterr().err == ""
