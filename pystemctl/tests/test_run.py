from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Sequence
from typing import Any

import anyio
import pytest
from conftest import BUS

from pystemctl.bus import Scope
from pystemctl.cli import helpers
from pystemctl.cli.args import RunArgs
from pystemctl.cli.commands import run as run_cmd
from pystemctl.cli.commands.run import _caller_environment
from pystemctl.systemd.tags import RESERVED


def _args(clean: bool = False) -> RunArgs:
    return RunArgs(clean=clean)


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


def _run_args(
    wait: bool = True,
    json: bool = False,
    shell: bool = False,
    command: Sequence[str] | None = None,
) -> RunArgs:
    return RunArgs(
        command=list(command) if command is not None else ["echo", "hi"],
        shell=shell,
        setenv=[],
        property=[],
        type="simple",
        description=None,
        working_directory=None,
        tags=[],
        slice_name=None,
        nice=None,
        runtime_max=None,
        remain_after_exit=False,
        collect=None,
        profile=None,
        unit="job.service",
        replace=False,
        no_block=False,
        wait=wait,
        session=None,
        json=json,
        scope=Scope.USER,
    )


def _following(
    monkeypatch: pytest.MonkeyPatch,
    lines: Sequence[str],
    seen: dict[str, object] | None = None,
) -> None:
    async def fake(**kwargs: object) -> AsyncIterator[str]:
        if seen is not None:
            seen.update(kwargs)
        for line in lines:
            yield line

    monkeypatch.setattr(helpers.jr, "follow_lines", fake)


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


def test_wait_streams_output_before_the_unit_name(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _finishing(monkeypatch)
    seen: dict[str, object] = {}
    _following(monkeypatch, ["hello"], seen)
    assert anyio.run(run_cmd.cmd_run, BUS, _run_args()) == 0
    captured = capsys.readouterr()
    # The command's output owns stdout; the unit name rides on stderr.
    assert captured.out.splitlines() == ["hello"]
    assert "job.service" in captured.err.splitlines()
    # run streams everything already written plus the live tail, notices
    # included, and never stops on a match it has no pattern for.
    assert seen["since_lines"] == 100
    assert seen["pattern"] is None
    assert seen["skip_notices"] is True


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


def test_detached_json_run_reports_the_shared_keys(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _finishing(monkeypatch)
    _following(monkeypatch, ["hello"])
    assert anyio.run(run_cmd.cmd_run, BUS, _run_args(wait=False, json=True)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["unit"] == "job.service"
    assert payload["active_state"] == "active"
    assert "exit_status" in payload
    assert "main_status" not in payload
