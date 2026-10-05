from __future__ import annotations

import argparse
import json

import pytest

from pystemctl.cli.commands.query import _query_states


def _args() -> argparse.Namespace:
    return argparse.Namespace(json=False)


def test_single_unit_prints_the_bare_state(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = _query_states(_args(), [("a.service", "active")], expected={"active"}, exit_code=3)
    assert code == 0
    assert capsys.readouterr().out == "active\n"


def test_several_units_are_named(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = _query_states(
        _args(),
        [("a.service", "active"), ("b.service", "inactive")],
        expected={"active"},
        exit_code=3,
    )
    assert code == 3
    assert capsys.readouterr().out.splitlines() == [
        "a.service: active",
        "b.service: inactive",
    ]


def test_json_names_the_queried_state(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = argparse.Namespace(json=True)
    code = _query_states(args, [("a.service", "active")], expected={"active"}, exit_code=3)
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == [{"unit": "a.service", "active_state": "active"}]


def test_json_names_file_states_for_is_enabled(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = argparse.Namespace(json=True)
    code = _query_states(
        args,
        [("a.service", "enabled")],
        expected={"enabled"},
        exit_code=1,
        state_key="unit_file_state",
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == [{"unit": "a.service", "unit_file_state": "enabled"}]
