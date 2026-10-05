from __future__ import annotations

import argparse
from collections.abc import Sequence

import anyio
import pytest
from conftest import BUS

from pystemctl.cli.commands import jobs as jobs_cmd
from pystemctl.systemd.jobs import Job
from pystemctl.systemd.units import Unit


def _unit(
    active_state: str = "active",
    sub_state: str = "running",
    name: str = "job.service",
) -> Unit:
    return Unit(
        name=name,
        description="a job",
        load_state="loaded",
        active_state=active_state,
        sub_state=sub_state,
        following="",
        path="/org/freedesktop/systemd1/unit/job_2eservice",
        job_id=0,
        job_type="",
        job_path="",
    )


def _job(session: str | None = None, name: str = "job.service", **props: object) -> Job:
    return Job(
        unit=_unit(name=name),
        tags=[],
        session=session,
        environment={},
        props=dict(props),
    )


def test_started_at_prefers_active_enter() -> None:
    job = _job(ActiveEnterTimestamp=100, ExecMainStartTimestamp=50, StateChangeTimestamp=10)
    assert job.started_at == 100


def test_started_at_falls_back_through_properties() -> None:
    assert _job(StateChangeTimestamp=7).started_at == 7
    assert _job(ExecMainStartTimestamp=9).started_at == 9


def test_started_at_ignores_missing_and_non_int() -> None:
    assert _job().started_at == 0
    assert _job(ActiveEnterTimestamp=None, StateChangeTimestamp="x").started_at == 0


def test_main_pid_reads_int_only() -> None:
    assert _job(MainPID=42).main_pid == 42
    assert _job(MainPID="x").main_pid == 0
    assert _job().main_pid == 0


def test_result_is_none_while_running() -> None:
    assert _job(Result="exit-code").result is None


def test_result_is_read_once_stopped() -> None:
    job = Job(
        unit=_unit("failed", "failed"),
        tags=[],
        session=None,
        environment={},
        props={"Result": "exit-code", "ExecMainStatus": 7},
    )
    assert job.result == "exit-code"
    assert job.exit_status == 7


def test_exit_status_only_for_exit_code_result() -> None:
    job = Job(
        unit=_unit("failed", "failed"),
        tags=[],
        session=None,
        environment={},
        props={"Result": "timeout", "ExecMainStatus": 0},
    )
    assert job.result == "timeout"
    assert job.exit_status is None


def _cmd_args(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "any_session": False,
        "session": None,
        "tags": [],
        "all": True,
        "all_transient": False,
        "follow": False,
        "json": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _collecting(
    monkeypatch: pytest.MonkeyPatch, found: dict[str | None, list[Job]]
) -> list[str | None]:
    """Stand in for collect_jobs; records the sessions it was asked for."""
    seen: list[str | None] = []

    async def fake(
        bus: object,
        *,
        required_tags: Sequence[str],
        session: str | None,
        include_inactive: bool,
    ) -> list[Job]:
        seen.append(session)
        return found.get(session, [])

    monkeypatch.setattr(jobs_cmd.sd, "collect_jobs", fake)
    return seen


def test_jobs_falls_back_to_any_session(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen = _collecting(monkeypatch, {None: [_job(session="other")]})
    code = anyio.run(jobs_cmd.cmd_jobs, BUS, _cmd_args(session="s1"))
    assert code == 0
    assert seen == ["s1", None]
    captured = capsys.readouterr()
    assert "job.service" in captured.out
    assert "every session" in captured.err


def test_jobs_skips_fallback_when_scoped_finds_jobs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen = _collecting(monkeypatch, {"s1": [_job(session="s1")], None: [_job(session="other")]})
    code = anyio.run(jobs_cmd.cmd_jobs, BUS, _cmd_args(session="s1"))
    assert code == 0
    assert seen == ["s1"]
    assert capsys.readouterr().err == ""


def test_jobs_reports_nothing_found(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen = _collecting(monkeypatch, {})
    code = anyio.run(jobs_cmd.cmd_jobs, BUS, _cmd_args(session="s1"))
    assert code == 1
    assert seen == ["s1", None]
    assert capsys.readouterr().out == ""


def test_jobs_any_session_queries_once(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen = _collecting(monkeypatch, {None: [_job(session="other")]})
    code = anyio.run(jobs_cmd.cmd_jobs, BUS, _cmd_args(any_session=True))
    assert code == 0
    assert seen == [None]
    capsys.readouterr()


def test_jobs_hides_foreign_units_by_default(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _collecting(
        monkeypatch,
        {"s1": [_job(session="s1", name="mine.service"), _job(name="other.service")]},
    )
    code = anyio.run(jobs_cmd.cmd_jobs, BUS, _cmd_args(session="s1"))
    assert code == 0
    out = capsys.readouterr().out
    assert "mine.service" in out
    assert "other.service" not in out


def test_jobs_all_transient_shows_everything(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _collecting(
        monkeypatch,
        {"s1": [_job(session="s1", name="mine.service"), _job(name="other.service")]},
    )
    code = anyio.run(jobs_cmd.cmd_jobs, BUS, _cmd_args(session="s1", all_transient=True))
    assert code == 0
    out = capsys.readouterr().out
    assert "mine.service" in out
    assert "other.service" in out


def test_jobs_names_hidden_foreign_units(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A session-less unit never survives the scoped query; the unscoped
    # retry is where the hidden count comes from.
    _collecting(monkeypatch, {"s1": [], None: [_job(name="other.service")]})
    code = anyio.run(jobs_cmd.cmd_jobs, BUS, _cmd_args(session="s1"))
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "hiding 1 transient unit" in captured.err
    assert "--all-transient" in captured.err


def test_jobs_any_session_counts_hidden_once(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without a session there is no retry; the one query's count stands."""
    _collecting(monkeypatch, {None: [_job(name="other.service")]})
    code = anyio.run(jobs_cmd.cmd_jobs, BUS, _cmd_args(any_session=True))
    assert code == 1
    assert "hiding 1 transient unit" in capsys.readouterr().err


def test_jobs_fallback_reports_unscoped_hidden_count(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The retry's wider view replaces the scoped count instead of adding."""
    _collecting(
        monkeypatch,
        {"s1": [], None: [_job(name="a.service"), _job(name="b.service")]},
    )
    code = anyio.run(jobs_cmd.cmd_jobs, BUS, _cmd_args(session="s1"))
    assert code == 1
    assert "hiding 2 transient units" in capsys.readouterr().err
