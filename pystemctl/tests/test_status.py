from __future__ import annotations

import argparse
import json

import anyio
import pytest
from conftest import BUS

from pystemctl.bus import Scope
from pystemctl.cli.commands import units as units_cmd
from pystemctl.errors import UnitNotFoundError
from pystemctl.systemd import Unit


def _args(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "units": [],
        "tags": [],
        "session": None,
        "lines": 10,
        "scope": Scope.USER,
        "json": False,
        "no_journal": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _properties(monkeypatch: pytest.MonkeyPatch, props: dict[str, object]) -> None:
    async def fake(bus: object, name: str) -> dict[str, object]:
        return props

    monkeypatch.setattr(units_cmd.sd, "unit_properties", fake)


def _journal(monkeypatch: pytest.MonkeyPatch, lines: list[str]) -> None:
    async def fake(unit: str, count: int, scope: object) -> list[str]:
        return lines

    monkeypatch.setattr(units_cmd, "journal_tail", fake)


def _trace(monkeypatch: pytest.MonkeyPatch, found: bool) -> None:
    async def fake(name: str, scope: object) -> bool:
        return found

    monkeypatch.setattr(units_cmd, "has_journal_trace", fake)


def test_status_explains_a_collected_unit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _properties(monkeypatch, {"LoadState": "not-found", "ActiveState": "inactive"})
    _trace(monkeypatch, True)
    _journal(monkeypatch, ["hello"])
    code = anyio.run(units_cmd.cmd_status, BUS, _args(units=["gone.service"]))
    assert code == 3
    out = capsys.readouterr().out
    assert "Collected" in out
    assert "not-found" not in out
    assert "hello" in out


def test_status_still_reports_a_loaded_unit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _properties(
        monkeypatch,
        {
            "LoadState": "loaded",
            "ActiveState": "active",
            "SubState": "running",
            "Description": "a job",
        },
    )
    _journal(monkeypatch, [])
    code = anyio.run(units_cmd.cmd_status, BUS, _args(units=["job.service"]))
    assert code == 0
    assert "* job.service" in capsys.readouterr().out


def test_status_collected_unit_json_carries_logs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _properties(monkeypatch, {"LoadState": "not-found", "ActiveState": "inactive"})
    _trace(monkeypatch, True)
    _journal(monkeypatch, ["hello"])
    code = anyio.run(units_cmd.cmd_status, BUS, _args(units=["gone.service"], json=True))
    assert code == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["journal"] == ["hello"]
    assert payload["load_state"] == "not-found"
    assert payload["active_state"] == "inactive"
    assert "load" not in payload
    assert "active" not in payload
    assert "sub" not in payload


def test_status_names_a_unit_that_never_ran(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No journal trace means the unit never ran: say so, not "collected"."""
    _properties(monkeypatch, {"LoadState": "not-found", "ActiveState": "inactive"})
    _trace(monkeypatch, False)
    code = anyio.run(units_cmd.cmd_status, BUS, _args(units=["typo.service"]))
    assert code == 4
    out = capsys.readouterr().out
    assert "Unit typo.service not found." in out
    assert "Collected" not in out


def test_status_never_ran_json_still_marks_not_found(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _properties(monkeypatch, {"LoadState": "not-found", "ActiveState": "inactive"})
    _trace(monkeypatch, False)
    _journal(monkeypatch, [])
    code = anyio.run(units_cmd.cmd_status, BUS, _args(units=["typo.service"], json=True))
    assert code == 4
    assert json.loads(capsys.readouterr().out)["journal"] == []


def test_status_invalid_name_reports_not_found(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A name LoadUnit refuses raises UnitNotFoundError; status says so.

    Well-formed missing names return a not-found path instead of raising,
    so this branch is only reachable for invalid names -- verified live
    with `status ///`, which LoadUnit rejects.
    """

    async def refuse(bus: object, name: str) -> dict[str, object]:
        raise UnitNotFoundError(name)

    monkeypatch.setattr(units_cmd.sd, "unit_properties", refuse)
    code = anyio.run(units_cmd.cmd_status, BUS, _args(units=["///.service"]))
    assert code == 4
    assert "Unit ///.service not found." in capsys.readouterr().out


def _listed_unit() -> Unit:
    return Unit(
        name="job.service",
        description="a job",
        load_state="loaded",
        active_state="active",
        sub_state="running",
        following="",
        path="/org/freedesktop/systemd1/unit/job_2eservice",
        job_id=0,
        job_type="",
        job_path="",
    )


def test_list_json_uses_the_shared_state_keys(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def listing(bus: object) -> list[Unit]:
        return [_listed_unit()]

    monkeypatch.setattr(units_cmd.sd, "list_units", listing)
    args = argparse.Namespace(all=True, type=None, state=None, ephemeral=False, json=True)
    assert anyio.run(units_cmd.cmd_list, BUS, args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == [
        {
            "unit": "job.service",
            "description": "a job",
            "load_state": "loaded",
            "active_state": "active",
            "sub_state": "running",
            "path": "/org/freedesktop/systemd1/unit/job_2eservice",
        }
    ]


def test_list_unit_files_json_names_the_file_state(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def listing(bus: object) -> list[tuple[str, str]]:
        return [("/usr/lib/systemd/system/a.service", "enabled")]

    monkeypatch.setattr(units_cmd.sd, "list_unit_files", listing)
    args = argparse.Namespace(type=None, state=None, json=True)
    assert anyio.run(units_cmd.cmd_list_unit_files, BUS, args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == [{"unit_file": "a.service", "unit_file_state": "enabled"}]
