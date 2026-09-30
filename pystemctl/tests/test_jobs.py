from __future__ import annotations

from pystemctl.systemd.jobs import Job
from pystemctl.systemd.units import Unit


def _unit(active_state: str = "active", sub_state: str = "running") -> Unit:
    return Unit(
        name="job.service",
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


def _job(**props: object) -> Job:
    return Job(
        unit=_unit(),
        tags=[],
        session=None,
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
