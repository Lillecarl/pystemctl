"""The entry point prints a user error and returns its exit code."""

from __future__ import annotations

import argparse
from collections.abc import Awaitable, Callable

import pytest

from pystemctl.cli import _run
from pystemctl.errors import PystemctlError, UnitNotFoundError


def _dispatch(error: Exception) -> Callable[[object], Awaitable[int]]:
    async def fail(args: object) -> int:
        raise error

    return fail


def test_entry_returns_the_errors_exit_code(capsys: pytest.CaptureFixture[str]) -> None:
    assert _run("pystemctl", argparse.ArgumentParser, _dispatch(UnitNotFoundError("x")), []) == 4
    assert "Unit x not found." in capsys.readouterr().err
    assert _run("pystemctl", argparse.ArgumentParser, _dispatch(PystemctlError("boom")), []) == 1
    assert "boom" in capsys.readouterr().err
