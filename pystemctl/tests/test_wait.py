from __future__ import annotations

import argparse
import json

import anyio
import pytest

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
    code = anyio.run(wait_cmd.cmd_wait, None, args)
    assert code == 124
    assert "timed out" in capsys.readouterr().err


def test_report_json_carries_the_exit_code(capsys: pytest.CaptureFixture[str]) -> None:
    outcome = WatchOutcome(props={"Result": "exit-code", "ExecMainStatus": 9})
    code = _report(_args(json_mode=True), "x.service", outcome)
    payload = json.loads(capsys.readouterr().out)
    assert payload["exit_code"] == 9
    assert payload["result"] == "exit-code"
    assert code == 9


class _Scope:
    def cancel(self) -> None:
        pass


class _Group:
    def __init__(self) -> None:
        self.cancel_scope = _Scope()


def test_pattern_watch_sees_manager_notices(monkeypatch: pytest.MonkeyPatch) -> None:
    """--grep runs against everything, so waiting on a notice still works."""
    seen: dict[str, object] = {}

    async def fake(
        name: object,
        args: object,
        outcome: WatchOutcome,
        group: object,
        *,
        replay: int,
        stop_on_match: bool,
        skip_notices: bool = True,
    ) -> None:
        seen["skip_notices"] = skip_notices

    monkeypatch.setattr(wait_cmd, "follow_matching", fake)
    args = argparse.Namespace(grep="Started", lines=None)
    anyio.run(
        wait_cmd._until_pattern_then_cancel, "x.service", args, WatchOutcome(), _Group()
    )
    assert seen["skip_notices"] is False
