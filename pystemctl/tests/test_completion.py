from __future__ import annotations

import argparse
import contextlib
from collections.abc import AsyncIterator, Sequence
from typing import Any

import pytest

from pystemctl import cli
from pystemctl.bus import Scope
from pystemctl.cli.parser import (
    _profile_completer,
    _unit_completer,
    build_journal_parser,
    build_parser,
    register_completers,
)


def test_argcomplete_marker_present() -> None:
    # argcomplete looks for this string in the first 1 KiB of the module the
    # console script imports, so it must stay near the top of pystemctl.cli.
    source = cli.__file__
    assert source is not None
    with open(source) as handle:
        assert "PYTHON_ARGCOMPLETE_OK" in handle.read(1024)


def test_parsers_build_for_completion() -> None:
    assert build_parser().prog == "pystemctl"
    assert build_journal_parser().prog == "pyjournalctl"


def _subparser(parser: argparse.ArgumentParser, name: str) -> argparse.ArgumentParser:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices[name]
    raise AssertionError(f"no subparsers in {parser.prog}")


def _action(parser: argparse.ArgumentParser, dest: str) -> argparse.Action:
    for action in parser._actions:
        if action.dest == dest:
            return action
    raise AssertionError(f"no {dest!r} in {parser.prog}")


def test_register_completers_attaches_unit_and_profile() -> None:
    parser = build_parser()
    register_completers(parser)
    assert _action(_subparser(parser, "status"), "units").completer is _unit_completer
    assert _action(_subparser(parser, "wait"), "unit").completer is _unit_completer
    assert _action(_subparser(parser, "run"), "profile").completer is _profile_completer
    assert _action(_subparser(parser, "profile"), "name").completer is _profile_completer

    journal = build_journal_parser()
    register_completers(journal)
    assert _action(journal, "system_units").completer is _unit_completer
    assert _action(journal, "user_units").completer is _unit_completer


class _StubBus:
    def __init__(self, rows: Sequence[Sequence[Any]]) -> None:
        self._rows = rows

    async def manager(self, *args: Any, **kwargs: Any) -> Any:
        assert args[:1] == ("ListUnits",)
        return (self._rows,)


def _connect_recorded_scopes(
    monkeypatch: pytest.MonkeyPatch, rows: Sequence[Sequence[Any]]
) -> list[Any]:
    scopes: list[Any] = []

    @contextlib.asynccontextmanager
    async def fake(scope: Scope) -> AsyncIterator[_StubBus]:
        scopes.append(scope)
        yield _StubBus(rows)

    monkeypatch.setattr("pystemctl.bus.connect", fake)
    return scopes


def _row(name: str) -> tuple[Any, ...]:
    return (name, "d", "loaded", "active", "running", "", "/p", 0, "", "")


def test_unit_completer_lists_matching_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scopes = _connect_recorded_scopes(
        monkeypatch, [_row("alpha.service"), _row("beta.service")]
    )
    assert _unit_completer("alp") == ["alpha.service"]
    assert scopes == [Scope.USER]


def test_unit_completer_honours_parsed_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scopes = _connect_recorded_scopes(monkeypatch, [_row("a.service")])
    parsed = argparse.Namespace(scope=Scope.SYSTEM)
    assert _unit_completer("", parsed) == ["a.service"]
    assert scopes == [Scope.SYSTEM]


def test_unit_completer_empty_on_bus_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @contextlib.asynccontextmanager
    async def broken(scope: Scope) -> AsyncIterator[Any]:
        raise RuntimeError("no bus")
        yield None

    monkeypatch.setattr("pystemctl.bus.connect", broken)
    assert _unit_completer("a") == []
