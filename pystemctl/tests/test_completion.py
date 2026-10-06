from __future__ import annotations

import argparse
import contextlib
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any, cast

import pytest
from conftest import make_job, make_unit

from pystemctl import cli
from pystemctl.bus import Scope
from pystemctl.cli.parser import (
    CompletableAction,
    _env_completer,
    _executable_completer,
    _priority_completer,
    _profile_completer,
    _service_property_completer,
    _session_completer,
    _show_property_completer,
    _slice_completer,
    _tags_completer,
    _unit_completer,
    _unit_file_completer,
    _unit_file_state_completer,
    _unit_state_completer,
    _unit_type_completer,
    build_journal_parser,
    build_parser,
    register_completers,
)
from pystemctl.journal.timestamps import PRIORITY_NAMES
from pystemctl.systemd.jobs import Job
from pystemctl.systemd.units import UNIT_SUFFIXES, Unit


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


def _action(parser: argparse.ArgumentParser, dest: str) -> CompletableAction:
    for action in parser._actions:
        if action.dest == dest:
            return cast(CompletableAction, action)
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
    assert _action(journal, "priority").completer is _priority_completer


def test_register_completers_prefers_command_overrides() -> None:
    parser = build_parser()
    register_completers(parser)
    assert _action(_subparser(parser, "enable"), "units").completer is _unit_file_completer
    assert _action(_subparser(parser, "disable"), "units").completer is _unit_file_completer
    assert _action(_subparser(parser, "list"), "type").completer is _unit_type_completer
    assert _action(_subparser(parser, "list"), "state").completer is _unit_state_completer
    state = _action(_subparser(parser, "list-unit-files"), "state")
    assert state.completer is _unit_file_state_completer
    run = _subparser(parser, "run")
    assert _action(run, "tags").completer is _tags_completer
    assert _action(run, "session").completer is _session_completer
    assert _action(run, "setenv").completer is _env_completer
    assert _action(run, "property").completer is _service_property_completer
    assert _action(run, "slice_name").completer is _slice_completer
    assert _action(run, "command").completer is _executable_completer
    # run's --type keeps argparse choices; no custom completer may shadow them.
    assert getattr(_action(run, "type"), "completer", None) is None
    assert _action(_subparser(parser, "show"), "properties").completer is (_show_property_completer)
    assert _action(_subparser(parser, "logs"), "priority").completer is _priority_completer


class _StubBus:
    def __init__(self, rows: Sequence[Sequence[Any]]) -> None:
        self._rows = rows

    async def manager(self, *args: Any, **kwargs: Any) -> Any:
        assert args[:1] == ("ListUnits",)
        return (self._rows,)


def _stub_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    """Yield a dummy bus; the query layer is faked separately."""

    @contextlib.asynccontextmanager
    async def fake(scope: Scope) -> AsyncIterator[Any]:
        yield object()

    monkeypatch.setattr("pystemctl.bus.connect", fake)


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
    scopes = _connect_recorded_scopes(monkeypatch, [_row("alpha.service"), _row("beta.service")])
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


def test_tags_completer_collects_distinct_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake(bus: Any, **kwargs: Any) -> list[Job]:
        return [make_job(tags=["b", "a"], session="s1"), make_job(tags=["a"])]

    monkeypatch.setattr("pystemctl.systemd.jobs.collect_jobs", fake)
    _stub_connect(monkeypatch)
    assert _tags_completer("a") == ["a"]
    assert _tags_completer("") == ["a", "b"]


def test_session_completer_skips_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake(bus: Any, **kwargs: Any) -> list[Job]:
        return [make_job(session="s2"), make_job(), make_job(session="s1")]

    monkeypatch.setattr("pystemctl.systemd.jobs.collect_jobs", fake)
    _stub_connect(monkeypatch)
    assert _session_completer("") == ["s1", "s2"]


def test_bus_completer_empty_on_query_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken(bus: Any, **kwargs: Any) -> list[Job]:
        raise RuntimeError("no jobs")

    monkeypatch.setattr("pystemctl.systemd.jobs.collect_jobs", broken)
    _stub_connect(monkeypatch)
    assert _tags_completer("") == []
    assert _session_completer("") == []


def test_slice_completer_keeps_slices_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake(bus: Any) -> list[Unit]:
        return [make_unit("app.slice"), make_unit("app.service")]

    monkeypatch.setattr("pystemctl.systemd.units.list_units", fake)
    _stub_connect(monkeypatch)
    assert _slice_completer("") == ["app.slice"]


def test_unit_file_completer_uses_basenames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake(bus: Any) -> list[tuple[str, str]]:
        return [("/usr/lib/systemd/system/b.service", "enabled")]

    monkeypatch.setattr("pystemctl.systemd.units.list_unit_files", fake)
    _stub_connect(monkeypatch)
    assert _unit_file_completer("b") == ["b.service"]


def test_show_property_completer_reads_target_unit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake(bus: Any, name: str) -> dict[str, Any]:
        assert name == "a.service"
        return {"Zebra": 1, "Apple": 2}

    monkeypatch.setattr("pystemctl.systemd.unit_properties", fake)
    _stub_connect(monkeypatch)
    parsed = argparse.Namespace(units=["a"], scope=Scope.USER)
    assert _show_property_completer("", parsed) == ["Apple", "Zebra"]
    assert _show_property_completer("", argparse.Namespace(units=[])) == []


def test_env_completer_stops_at_equals(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYSTEMCTL_TEST_COMPLETION_MARKER", "1")
    assert _env_completer("PYSTEMCTL_TEST_COMPLETION_M") == ["PYSTEMCTL_TEST_COMPLETION_MARKER"]
    assert _env_completer("PYSTEMCTL_TEST_COMPLETION_MARKER=") == []
    assert _env_completer("PYSTEMCTL_TEST_COMPLETION_MARKER=x") == []


def test_executable_completer_scans_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    script = tmp_path / "my-probe-tool"
    script.write_text("#!/bin/sh\n")
    script.chmod(0o755)
    (tmp_path / "not-executable").write_text("x")
    monkeypatch.setenv("PATH", str(tmp_path))
    assert _executable_completer("my-probe") == ["my-probe-tool"]
    assert _executable_completer("./my-probe") == []
    assert _executable_completer("", argparse.Namespace(command=["tool"])) == []


def test_static_completers_filter_by_prefix() -> None:
    assert _priority_completer("e") == ["emerg", "err"]
    assert _unit_type_completer("s") == ["service", "socket", "swap", "slice", "scope"]
    assert "enabled" in _unit_file_state_completer("")
    assert "active" in _unit_state_completer("")
    assert "MemoryMax" in _service_property_completer("Memory")


def test_completion_lists_track_their_sources() -> None:
    assert _unit_type_completer("") == [suffix.removeprefix(".") for suffix in UNIT_SUFFIXES]
    assert _priority_completer("") == list(PRIORITY_NAMES)
