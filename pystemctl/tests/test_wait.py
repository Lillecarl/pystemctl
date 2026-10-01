from __future__ import annotations

import argparse
import json

import pytest

from pystemctl.cli.commands.wait import _report
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


def test_report_json_carries_the_exit_code(capsys: pytest.CaptureFixture[str]) -> None:
    outcome = WatchOutcome(props={"Result": "exit-code", "ExecMainStatus": 9})
    code = _report(_args(json_mode=True), "x.service", outcome)
    payload = json.loads(capsys.readouterr().out)
    assert payload["exit_code"] == 9
    assert payload["result"] == "exit-code"
    assert payload["status"] == 9
    assert code == 9
