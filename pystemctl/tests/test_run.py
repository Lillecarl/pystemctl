from __future__ import annotations

import argparse
import json
import os
from collections.abc import AsyncIterator, Sequence
from typing import Any

import anyio
import pytest
from conftest import BUS, as_task_group

from pystemctl.bus import Scope
from pystemctl.cli.commands import run as run_cmd
from pystemctl.cli.commands.run import _caller_environment
from pystemctl.systemd.tags import RESERVED


def _args(clean: bool = False) -> argparse.Namespace:
    return argparse.Namespace(clean=clean)


def test_caller_environment_inherits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYSTEMCTL_TEST_MARKER", "1")
    environment = _caller_environment(_args())
    assert environment["PYSTEMCTL_TEST_MARKER"] == "1"
    assert environment == {k: v for k, v in os.environ.items() if k not in RESERVED}


def test_caller_environment_never_carries_reserved(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in RESERVED:
        monkeypatch.setenv(name, "spoofed")
    environment = _caller_environment(_args())
    assert all(name not in environment for name in RESERVED)


def test_caller_environment_clean_is_empty() -> None:
    assert _caller_environment(_args(clean=True)) == {}


class _Scope:
    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class _Group:
    def __init__(self) -> None:
        self.cancel_scope = _Scope()


def _run_args(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "command": ["echo", "hi"],
        "shell": False,
        "setenv": [],
        "property": [],
        "type": "simple",
        "description": None,
        "working_directory": None,
        "tags": [],
        "slice_name": None,
        "nice": None,
        "runtime_max": None,
        "remain_after_exit": False,
        "collect": None,
        "profile": None,
        "unit": "job.service",
        "replace": False,
        "no_block": False,
        "wait": True,
        "session": None,
        "json": False,
        "scope": Scope.USER,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _following(monkeypatch: pytest.MonkeyPatch, lines: Sequence[str]) -> None:
    async def fake(**_: object) -> AsyncIterator[str]:
        for line in lines:
            yield line

    monkeypatch.setattr(run_cmd.jr, "follow_lines", fake)


def _finishing(monkeypatch: pytest.MonkeyPatch) -> None:
    async def start(bus: object, spec: object, mode: str = "fail") -> str:
        return "job"

    async def started(bus: object, job: str) -> str:
        return "done"

    async def finished(bus: object, name: str) -> dict[str, object]:
        return {"Result": "success", "ActiveState": "inactive", "ExecMainStatus": 0}

    async def current(bus: object, name: str) -> dict[str, object]:
        return {"ActiveState": "active", "SubState": "running"}

    monkeypatch.setattr(run_cmd.sd, "start_transient", start)
    monkeypatch.setattr(run_cmd.sd, "wait_job", started)
    monkeypatch.setattr(run_cmd.sd, "wait_until_finished", finished)
    monkeypatch.setattr(run_cmd.sd, "try_unit_properties", current)


def test_stream_prints_output_lines(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _following(monkeypatch, ["l1", "l2"])
    group = _Group()
    anyio.run(run_cmd._stream, "job.service", _run_args(), as_task_group(group))
    assert capsys.readouterr().out.splitlines() == ["l1", "l2"]
    assert group.cancel_scope.cancelled


def test_watch_records_properties_and_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _finishing(monkeypatch)
    outcome = run_cmd.WatchOutcome()
    group = _Group()
    anyio.run(run_cmd._watch, BUS, "job.service", outcome, as_task_group(group))
    assert outcome.props["Result"] == "success"
    assert group.cancel_scope.cancelled


def test_wait_streams_output_before_the_unit_name(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _finishing(monkeypatch)
    _following(monkeypatch, ["hello"])
    assert anyio.run(run_cmd.cmd_run, BUS, _run_args()) == 0
    captured = capsys.readouterr()
    # The command's output owns stdout; the unit name rides on stderr.
    assert captured.out.splitlines() == ["hello"]
    assert "job.service" in captured.err.splitlines()


def test_detached_run_hints_at_logs_and_wait(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _finishing(monkeypatch)
    _following(monkeypatch, ["hello"])
    assert anyio.run(run_cmd.cmd_run, BUS, _run_args(wait=False)) == 0
    captured = capsys.readouterr()
    assert captured.out == "job.service\n"
    assert "pystemctl logs job.service" in captured.err
    assert "pystemctl wait job.service" in captured.err


def test_json_run_stays_quiet(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _finishing(monkeypatch)
    _following(monkeypatch, ["hello"])
    assert anyio.run(run_cmd.cmd_run, BUS, _run_args(wait=False, json=True)) == 0
    assert capsys.readouterr().err == ""


def test_wait_json_stays_a_single_payload(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _finishing(monkeypatch)
    _following(monkeypatch, ["hello"])
    assert anyio.run(run_cmd.cmd_run, BUS, _run_args(json=True)) == 0
    out = capsys.readouterr().out
    assert "hello" not in out
    assert json.loads(out)["unit"] == "job.service"


def test_shell_quotes_arguments(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[Any] = []

    async def start(bus: object, spec: Any, mode: str = "fail") -> str:
        seen.append(spec)
        return "job"

    async def started(bus: object, job: str) -> str:
        return "done"

    async def current(bus: object, name: str) -> dict[str, object]:
        return {"ActiveState": "active"}

    monkeypatch.setattr(run_cmd.sd, "start_transient", start)
    monkeypatch.setattr(run_cmd.sd, "wait_job", started)
    monkeypatch.setattr(run_cmd.sd, "try_unit_properties", current)
    args = _run_args(wait=False, shell=True, command=["echo", "a  b"])
    assert anyio.run(run_cmd.cmd_run, BUS, args) == 0
    assert seen[0].argv[2] == "echo 'a  b'"
    capsys.readouterr()
