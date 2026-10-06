from __future__ import annotations

from collections.abc import AsyncIterator
from functools import partial

import anyio
import pytest
from conftest import BUS, FakeTaskGroup, as_task_group

from pystemctl.bus import Scope
from pystemctl.cli import helpers
from pystemctl.cli.args import TailArgs, WatchArgs
from pystemctl.cli.commands import tail as tail_cmd
from pystemctl.cli.helpers import Target, TargetHow, WatchOutcome
from pystemctl.errors import PystemctlError


@pytest.mark.parametrize(
    ("grep", "skipped", "code", "logged"),
    [(None, True, 0, ["unrelated"]), ("ERROR", False, 1, [])],
)
def test_follow_hides_notices_unless_grepping(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    grep: str | None,
    skipped: bool,
    code: int,
    logged: list[str],
) -> None:
    """--grep matches everything, including the manager's lifecycle lines."""
    seen: dict[str, object] = {}

    async def lines(**kwargs: object) -> AsyncIterator[str]:
        seen.update(kwargs)
        for line in logged:
            yield line

    async def resolve(bus: object, args: object) -> tuple[Target, dict[str, object]]:
        return Target("x.service", TargetHow.EXPLICIT), {
            "ActiveState": "active",
            "SubState": "running",
        }

    async def finished(bus: object, name: str) -> dict[str, object]:
        return {"ActiveState": "inactive", "Type": "service", "Result": "success"}

    monkeypatch.setattr(helpers.jr, "follow_lines", lines)
    monkeypatch.setattr(tail_cmd, "resolve_existing", resolve)
    monkeypatch.setattr(tail_cmd.sd, "wait_until_finished", finished)
    assert anyio.run(tail_cmd.cmd_tail, BUS, _tail_args(grep=grep)) == code
    assert seen["skip_notices"] is skipped
    capsys.readouterr()


def test_follow_matching_tolerates_commands_without_grep(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """run --wait streams through here but its parser defines no --grep."""
    seen: dict[str, object] = {}

    async def fake(**kwargs: object) -> AsyncIterator[str]:
        seen.update(kwargs)
        yield "hello"

    monkeypatch.setattr(helpers.jr, "follow_lines", fake)
    args = WatchArgs(json=False, scope=Scope.USER)
    watch = partial(
        helpers.follow_matching,
        "x.service",
        args,
        WatchOutcome(),
        as_task_group(FakeTaskGroup()),
        replay=10,
        stop_on_match=False,
        skip_notices=True,
    )
    anyio.run(watch)
    assert seen["pattern"] is None
    assert capsys.readouterr().out == "hello\n"


def test_follow_matching_forwards_the_flag(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, object] = {}

    async def fake(**kwargs: object) -> AsyncIterator[str]:
        seen.update(kwargs)
        yield "hello"

    monkeypatch.setattr(helpers.jr, "follow_lines", fake)
    group = as_task_group(FakeTaskGroup())
    args = TailArgs(grep=None, json=False, scope=Scope.USER)
    watch = partial(
        helpers.follow_matching,
        "x.service",
        args,
        WatchOutcome(),
        group,
        replay=10,
        stop_on_match=False,
        skip_notices=False,
    )
    anyio.run(watch)
    assert seen["skip_notices"] is False
    assert seen["pattern"] is None
    assert capsys.readouterr().out == "hello\n"


def test_follow_matching_skips_notices_by_default(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, object] = {}

    async def fake(**kwargs: object) -> AsyncIterator[str]:
        seen.update(kwargs)
        yield "hello"

    monkeypatch.setattr(helpers.jr, "follow_lines", fake)
    args = TailArgs(grep=None, json=False, scope=Scope.USER)
    watch = partial(
        helpers.follow_matching,
        "x.service",
        args,
        WatchOutcome(),
        as_task_group(FakeTaskGroup()),
        replay=10,
        stop_on_match=False,
    )
    anyio.run(watch)
    assert seen["skip_notices"] is True
    capsys.readouterr()


def _stall_tail(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve a running unit, then never observe anything more."""

    async def resolve(bus: object, args: object) -> tuple[Target, dict[str, object]]:
        return Target("x.service", TargetHow.EXPLICIT), {
            "ActiveState": "active",
            "SubState": "running",
        }

    async def slow_finished(bus: object, name: str) -> dict[str, object]:
        await anyio.sleep(30)
        return {}

    async def slow_lines(**kwargs: object) -> AsyncIterator[str]:
        await anyio.sleep(30)
        yield "never"

    monkeypatch.setattr(tail_cmd, "resolve_existing", resolve)
    monkeypatch.setattr(tail_cmd.sd, "wait_until_finished", slow_finished)
    monkeypatch.setattr(helpers.jr, "follow_lines", slow_lines)


def _tail_args(grep: str | None = None, until_exit: bool = False) -> TailArgs:
    return TailArgs(
        unit="x.service",
        lines=None,
        follow=True,
        until_exit=until_exit,
        grep=grep,
        timeout=0.05,
        json=False,
        scope=Scope.USER,
    )


def _bare_tail_args(grep: str | None = None) -> TailArgs:
    # What from_namespace builds without -f: follow until the end by default.
    return TailArgs(
        unit="x.service",
        lines=None,
        follow=False,
        until_exit=True,
        grep=grep,
        timeout=0.05,
        json=False,
        scope=Scope.USER,
    )


def _collected_tail(monkeypatch: pytest.MonkeyPatch, journal: list[dict[str, object]]) -> None:
    """Fail resolution as collected, serve the given journal for replay."""

    async def resolve(bus: object, args: object) -> tuple[Target, dict[str, object]]:
        raise PystemctlError("Unit x.service already finished and was collected")

    async def entries(reader: object, **kwargs: object) -> AsyncIterator[dict[str, object]]:
        for entry in journal:
            yield entry

    monkeypatch.setattr(tail_cmd, "resolve_existing", resolve)
    monkeypatch.setattr(helpers.jr, "open_reader", lambda **kwargs: object())
    monkeypatch.setattr(helpers.jr, "entries", entries)


def _manager_line(message: str) -> dict[str, object]:
    return {"SYSLOG_IDENTIFIER": "systemd", "MESSAGE": message}


def _program_line(message: str) -> dict[str, object]:
    return {"SYSLOG_IDENTIFIER": "bash", "MESSAGE": message}


def test_tail_replays_a_collected_unit_and_reports_its_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _collected_tail(
        monkeypatch,
        [
            _program_line("hello"),
            _manager_line("Started x.service."),
            _manager_line("x.service: Main process exited, code=exited, status=3/NOTIMPLEMENTED"),
            _manager_line("x.service: Failed with result 'exit-code'."),
        ],
    )
    code = anyio.run(tail_cmd.cmd_tail, BUS, _bare_tail_args())
    assert code == 3
    captured = capsys.readouterr()
    assert "hello" in captured.out
    assert "already finished and was collected" in captured.err


def test_tail_reports_zero_for_a_clean_collected_unit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _collected_tail(monkeypatch, [_manager_line("Started x.service.")])
    assert anyio.run(tail_cmd.cmd_tail, BUS, _bare_tail_args()) == 0


def test_tail_grep_on_a_collected_unit_answers_matched_or_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = [
        _program_line("all good"),
        _manager_line("Started x.service."),
    ]
    _collected_tail(monkeypatch, journal)
    assert anyio.run(tail_cmd.cmd_tail, BUS, _bare_tail_args(grep="good")) == 0
    _collected_tail(monkeypatch, journal)
    assert anyio.run(tail_cmd.cmd_tail, BUS, _bare_tail_args(grep="ERROR")) == 1


def test_tail_follow_on_a_collected_unit_streams_without_judging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Explicit -f keeps the plain stream, which always exits 0.
    _collected_tail(
        monkeypatch,
        [
            _manager_line("Started x.service."),
            _manager_line("x.service: Main process exited, code=exited, status=3/NOTIMPLEMENTED"),
            _manager_line("x.service: Failed with result 'exit-code'."),
        ],
    )
    assert anyio.run(tail_cmd.cmd_tail, BUS, _tail_args()) == 0


def test_tail_keeps_the_error_without_a_journal_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _collected_tail(monkeypatch, [])
    with pytest.raises(PystemctlError, match="already finished and was collected"):
        anyio.run(tail_cmd.cmd_tail, BUS, _bare_tail_args())


def test_tail_until_exit_on_a_stopped_unit_returns_without_following(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dead unit's replay prints and the stream ends; it never follows."""
    seen: dict[str, object] = {}

    async def lines(**kwargs: object) -> AsyncIterator[str]:
        seen.update(kwargs)
        return
        yield  # pragma: no cover -- makes this an empty async generator

    async def resolve(bus: object, args: object) -> tuple[Target, dict[str, object]]:
        props: dict[str, object] = {
            "ActiveState": "failed",
            "Type": "service",
            "Result": "exit-code",
            "ExecMainStatus": 3,
        }
        return Target("x.service", TargetHow.EXPLICIT), props

    monkeypatch.setattr(tail_cmd, "resolve_existing", resolve)
    monkeypatch.setattr(helpers.jr, "follow_lines", lines)
    assert anyio.run(tail_cmd.cmd_tail, BUS, _tail_args(until_exit=True)) == 3
    assert seen["follow"] is False


def test_tail_until_exit_timeout_is_not_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stall_tail(monkeypatch)
    code = anyio.run(tail_cmd.cmd_tail, BUS, _tail_args(until_exit=True))
    assert code == 124
    assert "timed out" in capsys.readouterr().err


def test_tail_grep_timeout_reports_no_match(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stall_tail(monkeypatch)
    code = anyio.run(tail_cmd.cmd_tail, BUS, _tail_args(grep="READY"))
    assert code == 1
    assert "timed out" in capsys.readouterr().err


def test_tail_plain_follow_timeout_stays_quiet(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A bounded plain follow printed what arrived; stopping there is the job.
    _stall_tail(monkeypatch)
    code = anyio.run(tail_cmd.cmd_tail, BUS, _tail_args())
    assert code == 0
    assert "timed out" in capsys.readouterr().err
