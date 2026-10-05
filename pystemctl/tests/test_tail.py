from __future__ import annotations

from collections.abc import AsyncIterator
from functools import partial

import anyio
import pytest
from conftest import BUS, as_task_group

from pystemctl.bus import Scope
from pystemctl.cli import helpers
from pystemctl.cli.args import TailArgs, WatchArgs
from pystemctl.cli.commands import tail as tail_cmd
from pystemctl.cli.helpers import WatchOutcome


class _Scope:
    def cancel(self) -> None:
        pass


class _Group:
    def __init__(self) -> None:
        self.cancel_scope = _Scope()


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

    async def resolve(bus: object, args: object) -> tuple[str, dict[str, object]]:
        return "x.service", {"ActiveState": "active", "SubState": "running"}

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
        as_task_group(_Group()),
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
    group = as_task_group(_Group())
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
        as_task_group(_Group()),
        replay=10,
        stop_on_match=False,
    )
    anyio.run(watch)
    assert seen["skip_notices"] is True
    capsys.readouterr()


def _stall_tail(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve a running unit, then never observe anything more."""

    async def resolve(bus: object, args: object) -> tuple[str, dict[str, object]]:
        return "x.service", {"ActiveState": "active", "SubState": "running"}

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
        lines=None,
        follow=True,
        until_exit=until_exit,
        grep=grep,
        timeout=0.05,
        json=False,
        scope=Scope.USER,
    )


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
