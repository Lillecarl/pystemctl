from __future__ import annotations

import argparse
import json

import anyio
import pytest

from pystemctl.bus import Scope
from pystemctl.cli.commands import units as units_cmd


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


def test_status_explains_a_collected_unit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _properties(
        monkeypatch, {"LoadState": "not-found", "ActiveState": "inactive"}
    )
    _journal(monkeypatch, ["hello"])
    code = anyio.run(units_cmd.cmd_status, None, _args(units=["gone.service"]))
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
    code = anyio.run(units_cmd.cmd_status, None, _args(units=["job.service"]))
    assert code == 0
    assert "* job.service" in capsys.readouterr().out


def test_status_collected_unit_json_carries_logs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _properties(
        monkeypatch, {"LoadState": "not-found", "ActiveState": "inactive"}
    )
    _journal(monkeypatch, ["hello"])
    code = anyio.run(
        units_cmd.cmd_status, None, _args(units=["gone.service"], json=True)
    )
    assert code == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["journal"] == ["hello"]
