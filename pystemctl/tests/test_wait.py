from __future__ import annotations

import argparse
import json
from collections.abc import AsyncIterator
from typing import cast

import anyio
import pytest
from conftest import BUS

from pystemctl.bus import Bus, Scope
from pystemctl.cli import helpers
from pystemctl.cli.commands import wait as wait_cmd
from pystemctl.cli.commands.wait import _report, _report_timeout
from pystemctl.cli.helpers import WatchOutcome


def _args(json_mode: bool = False) -> argparse.Namespace:
    return argparse.Namespace(json=json_mode)


@pytest.mark.parametrize(
    ("props", "expected"),
    [
        ({"Result": "success", "ExecMainStatus": 0}, 0),
        ({"Result": "exit-code", "ExecMainStatus": 7}, 7),
        ({"Result": "exit-code", "ExecMainStatus": 42}, 42),
        ({"Result": "timeout", "ExecMainStatus": 0}, 1),
        ({"Result": "signal", "ExecMainStatus": 0}, 1),
    ],
)
def test_report_returns_the_job_exit_code(props: dict[str, object], expected: int) -> None:
    assert _report(_args(), "x.service", WatchOutcome(props=props)) == expected


def test_report_matched_is_success() -> None:
    outcome = WatchOutcome(props={"Result": "exit-code", "ExecMainStatus": 7}, matched=True)
    assert _report(_args(), "x.service", outcome) == 0


def test_report_no_result_reads_as_success() -> None:
    # A collected unit's properties are empty; there is nothing to report but
    # a clean exit, so that is what it says.
    assert _report(_args(), "x.service", WatchOutcome(props={})) == 0


def test_report_timeout_names_the_timeout(capsys: pytest.CaptureFixture[str]) -> None:
    args = argparse.Namespace(json=False, timeout=3)
    code = _report_timeout(args, "x.service", WatchOutcome(props={}))
    assert code == 124
    assert "timed out after 3s" in capsys.readouterr().err


def test_report_timeout_json_marks_the_giveup(capsys: pytest.CaptureFixture[str]) -> None:
    args = argparse.Namespace(json=True, timeout=2.5)
    code = _report_timeout(args, "x.service", WatchOutcome(props={}))
    payload = json.loads(capsys.readouterr().out)
    assert payload["timed_out"] is True
    assert payload["timeout"] == 2.5
    assert payload["exit_code"] == 124
    assert code == 124


def test_cmd_wait_timeout_is_not_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A wait that outlives its --timeout must not read as success."""

    async def resolve(bus: object, args: object) -> tuple[str, dict[str, object]]:
        return "x.service", {}

    async def slow(bus: object, name: str) -> dict[str, object]:
        await anyio.sleep(30)
        return {}

    monkeypatch.setattr(wait_cmd, "resolve_existing", resolve)
    monkeypatch.setattr(wait_cmd.sd, "wait_until_finished", slow)
    monkeypatch.setattr(wait_cmd.sd, "try_unit_properties", slow)
    args = argparse.Namespace(timeout=0.05, grep=None, json=False)
    code = anyio.run(wait_cmd.cmd_wait, BUS, args)
    assert code == 124
    assert "timed out" in capsys.readouterr().err


def test_report_json_carries_the_exit_code(capsys: pytest.CaptureFixture[str]) -> None:
    outcome = WatchOutcome(props={"Result": "exit-code", "ExecMainStatus": 9})
    code = _report(_args(json_mode=True), "x.service", outcome)
    payload = json.loads(capsys.readouterr().out)
    assert payload["exit_code"] == 9
    assert payload["result"] == "exit-code"
    assert payload["exit_status"] == 9
    assert "status" not in payload
    assert code == 9


def test_wait_matches_lifecycle_notices(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """--grep matches everything, including the manager's lifecycle lines."""

    async def resolve(bus: object, args: object) -> tuple[str, dict[str, object]]:
        return "x.service", {}

    async def finished(bus: object, name: str) -> dict[str, object]:
        return {"ActiveState": "inactive", "Type": "service", "Result": "success"}

    async def lines(**kwargs: object) -> AsyncIterator[str]:
        yield "Started x.service."

    monkeypatch.setattr(wait_cmd, "resolve_existing", resolve)
    monkeypatch.setattr(wait_cmd.sd, "wait_until_finished", finished)
    monkeypatch.setattr(helpers.jr, "follow_lines", lines)
    args = argparse.Namespace(
        timeout=None, grep="Started", lines=None, json=False, scope=Scope.USER
    )
    assert anyio.run(wait_cmd.cmd_wait, BUS, args) == 0
    captured = capsys.readouterr()
    assert "Started x.service." in captured.out
    assert "pattern matched" in captured.err


@pytest.mark.parametrize(
    ("props", "expected"),
    [
        ({"ActiveState": "inactive", "Type": "service", "Result": "success"}, True),
        ({"ActiveState": "failed", "Type": "service", "Result": "exit-code"}, True),
        # A oneshot parked by RemainAfterExit is finished: its process is
        # gone and only the remembered result remains.
        (
            {
                "ActiveState": "active",
                "SubState": "exited",
                "Type": "service",
                "Result": "success",
                "ExecMainStatus": 0,
            },
            True,
        ),
        # Still running is not finished, whatever the substate claims.
        ({"ActiveState": "active", "SubState": "running", "Type": "service"}, False),
        # Parked but result not yet reported: the exit code is still unknown.
        ({"ActiveState": "active", "SubState": "exited", "Type": "service"}, False),
        # A queued job means a transition is still in flight.
        (
            {
                "ActiveState": "inactive",
                "Type": "service",
                "Result": "success",
                "Job": (1, "/org/freedesktop/systemd1/job/1"),
            },
            False,
        ),
    ],
)
def test_unit_finished_recognises_parked_oneshots(props: dict[str, object], expected: bool) -> None:
    assert wait_cmd.sd.unit_finished(props) == expected


class _ParkedMessage:
    body = ("", {}, [])


class _ParkedQueue:
    async def get(self) -> _ParkedMessage:
        return _ParkedMessage()


class _ParkedFilter:
    def __init__(self, queue: _ParkedQueue) -> None:
        self._queue = queue

    def __enter__(self) -> _ParkedQueue:
        return self._queue

    def __exit__(self, *exc: object) -> None:
        return None


class _ParkedBus:
    """A bus whose unit is already parked in active/exited."""

    def __init__(self, props: dict[str, object]) -> None:
        self._props = props

    async def manager(
        self, method: object, signature: object = None, body: object = ()
    ) -> tuple[str]:
        return ("/org/freedesktop/systemd1/unit/x",)

    async def add_match(self, rule: object) -> None:
        pass

    def filter(self, rule: object, *, queue: object = None) -> _ParkedFilter:
        return _ParkedFilter(_ParkedQueue())

    async def get_all(self, path: str, interface: str) -> dict[str, object]:
        return dict(self._props)


def test_wait_until_finished_returns_parked_result() -> None:
    """An already-parked unit resolves at once instead of hanging."""
    parked: dict[str, object] = {
        "ActiveState": "active",
        "SubState": "exited",
        "Type": "service",
        "Result": "exit-code",
        "ExecMainStatus": 3,
    }
    bus = cast(Bus, _ParkedBus(parked))

    async def _wait_soon() -> dict[str, object]:
        with anyio.fail_after(5):
            return await wait_cmd.sd.wait_until_finished(bus, "x.service", None)

    props = anyio.run(_wait_soon)
    assert props["Result"] == "exit-code"
    assert props["ExecMainStatus"] == 3
