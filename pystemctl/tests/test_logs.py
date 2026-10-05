from __future__ import annotations

import anyio
import pytest
from conftest import BUS

from pystemctl.bus import Scope
from pystemctl.cli.commands import logs as logs_cmd
from pystemctl.cli.helpers import Target, TargetHow


def _explicit(name: str) -> Target:
    return Target(name, TargetHow.EXPLICIT)


def _setup(
    monkeypatch: pytest.MonkeyPatch,
    props: dict[str, object],
    trace: bool,
) -> dict[str, object]:
    seen: dict[str, object] = {}

    async def properties(bus: object, name: str) -> dict[str, object]:
        return props

    async def has_trace(name: str, scope: object) -> bool:
        seen["traced"] = True
        return trace

    monkeypatch.setattr(logs_cmd.sd, "try_unit_properties", properties)
    monkeypatch.setattr(logs_cmd, "has_journal_trace", has_trace)
    return seen


def test_drop_unknown_removes_a_name_that_never_ran(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _setup(monkeypatch, {"LoadState": "not-found"}, trace=False)
    kept = anyio.run(logs_cmd._drop_unknown, BUS, [_explicit("typo.service")], Scope.USER)
    assert kept == []
    assert "not found" in capsys.readouterr().err


def test_drop_unknown_keeps_a_collected_job(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _setup(monkeypatch, {"LoadState": "not-found"}, trace=True)
    kept = anyio.run(
        logs_cmd._drop_unknown,
        BUS,
        [Target("old.service", TargetHow.COLLECTED)],
        Scope.USER,
    )
    assert kept == ["old.service"]
    assert capsys.readouterr().err == ""


def test_drop_unknown_keeps_a_loaded_unit_without_asking_the_journal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _setup(monkeypatch, {"LoadState": "loaded", "ActiveState": "active"}, trace=False)
    kept = anyio.run(logs_cmd._drop_unknown, BUS, [_explicit("job.service")], Scope.USER)
    assert kept == ["job.service"]
    assert "traced" not in seen


def test_drop_unknown_trusts_a_tag_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A tag already resolved to something real; re-checking it here would
    # second-guess the resolver.
    seen = _setup(monkeypatch, {}, trace=False)
    kept = anyio.run(
        logs_cmd._drop_unknown, BUS, [Target("job.service", TargetHow.TAG)], Scope.USER
    )
    assert kept == ["job.service"]
    assert "traced" not in seen
