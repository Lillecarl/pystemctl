from __future__ import annotations

from collections.abc import Sequence

import anyio
import pytest
from conftest import BUS

from pystemctl import systemd as sd
from pystemctl.bus import Scope
from pystemctl.cli import helpers
from pystemctl.cli.args import MultiTargetArgs, SingleTargetArgs
from pystemctl.cli.helpers import Target, TargetHow
from pystemctl.cli.parser import build_parser
from pystemctl.errors import PystemctlError
from pystemctl.systemd.jobs import Job
from pystemctl.systemd.units import Unit


def _unit(name: str) -> Unit:
    return Unit(
        name=name,
        description="a job",
        load_state="loaded",
        active_state="active",
        sub_state="running",
        following="",
        path="/org/freedesktop/systemd1/unit/x",
        job_id=0,
        job_type="",
        job_path="",
    )


def _job(name: str) -> Job:
    return Job(unit=_unit(name), tags=["t"], session=None, environment={}, props={})


def _args(units: list[str] | None = None, tags: list[str] | None = None) -> MultiTargetArgs:
    return MultiTargetArgs(units=units or [], tags=tags or [], session=None)


def _resolving(
    monkeypatch: pytest.MonkeyPatch, chosen: Job | None, rest: Sequence[Job] = ()
) -> None:
    async def fake(
        bus: object, *, tags: Sequence[str] = (), **_: object
    ) -> tuple[Job | None, list[Job]]:
        assert tags, "resolve called without tags"
        return chosen, list(rest)

    monkeypatch.setattr(sd, "resolve", fake)


def test_units_only_are_normalized_without_touching_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _resolving(monkeypatch, _job("new.service"))
    assert anyio.run(helpers.resolve_many, BUS, _args(units=["web"])) == [
        Target("web.service", TargetHow.EXPLICIT)
    ]


def test_tag_appends_the_newest_match(monkeypatch: pytest.MonkeyPatch) -> None:
    _resolving(monkeypatch, _job("new.service"), [_job("old.service")])
    targets = anyio.run(helpers.resolve_many, BUS, _args(units=["web"], tags=["t"]))
    assert targets == [
        Target("web.service", TargetHow.EXPLICIT),
        Target("new.service", TargetHow.TAG),
    ]


def test_other_matches_are_named_on_stderr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _resolving(monkeypatch, _job("new.service"), [_job("old.service")])
    anyio.run(helpers.resolve_many, BUS, _args(tags=["t"]))
    assert "old.service" in capsys.readouterr().err


def test_tag_miss_propagates_resolve_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def missing(bus: object, **_: object) -> tuple[Job | None, list[Job]]:
        raise PystemctlError("no job tagged t")

    monkeypatch.setattr(sd, "resolve", missing)
    with pytest.raises(PystemctlError, match="no job tagged"):
        anyio.run(helpers.resolve_many, BUS, _args(tags=["t"]))


def test_neither_unit_nor_tag_is_an_error() -> None:
    with pytest.raises(PystemctlError, match="give a unit name"):
        anyio.run(helpers.resolve_many, BUS, _args())


def test_single_target_uses_a_name_as_given() -> None:
    args = SingleTargetArgs(unit="web", tags=[], scope=Scope.USER)
    assert anyio.run(helpers.resolve_one, BUS, args) == Target("web.service", TargetHow.EXPLICIT)


def test_single_target_without_either_is_an_error() -> None:
    with pytest.raises(PystemctlError, match="no unit or tag given"):
        anyio.run(helpers.resolve_one, BUS, SingleTargetArgs())


def test_single_target_reports_how_it_resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    _resolving(monkeypatch, _job("new.service"))
    args = SingleTargetArgs(unit=None, tags=["t"], scope=Scope.USER)
    assert anyio.run(helpers.resolve_one, BUS, args) == Target("new.service", TargetHow.TAG)


@pytest.mark.parametrize("command", ["logs", "status"])
def test_logs_and_status_take_a_tag(command: str) -> None:
    args = build_parser().parse_args([command, "--tag", "backups"])
    assert args.tags == ["backups"]
    assert args.units == []
