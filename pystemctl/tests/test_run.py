from __future__ import annotations

import argparse
import os

import pytest

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
