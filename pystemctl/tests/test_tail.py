from __future__ import annotations

import argparse
from collections.abc import AsyncIterator
from functools import partial

import anyio
import pytest

from pystemctl.bus import Scope
from pystemctl.cli import helpers
from pystemctl.cli.commands import tail as tail_cmd
from pystemctl.cli.helpers import WatchOutcome


class _Scope:
    def cancel(self) -> None:
        pass


class _Group:
    def __init__(self) -> None:
        self.cancel_scope = _Scope()


@pytest.mark.parametrize(
    ("grep", "skipped"),
    [(None, True), ("ERROR", False)],
)
def test_stream_hides_notices_unless_grepping(
    monkeypatch: pytest.MonkeyPatch, grep: str | None, skipped: bool
) -> None:
    """--grep matches everything, including the manager's lifecycle lines."""
    seen: dict[str, object] = {}

    async def fake(
        name: object,
        args: object,
        outcome: WatchOutcome,
        group: object,
        *,
        replay: int,
        stop_on_match: bool,
        skip_notices: bool = True,
    ) -> None:
        seen["skip_notices"] = skip_notices

    monkeypatch.setattr(tail_cmd, "follow_matching", fake)
    args = argparse.Namespace(grep=grep)
    anyio.run(tail_cmd._stream, "x.service", args, WatchOutcome(), 200, _Group())
    assert seen["skip_notices"] is skipped


def test_follow_matching_forwards_the_flag(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: dict[str, object] = {}

    async def fake(**kwargs: object) -> AsyncIterator[str]:
        seen.update(kwargs)
        yield "hello"

    monkeypatch.setattr(helpers.jr, "follow_lines", fake)
    group = _Group()
    args = argparse.Namespace(grep=None, json=False, scope=Scope.USER)
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
    args = argparse.Namespace(grep=None, json=False, scope=Scope.USER)
    watch = partial(
        helpers.follow_matching,
        "x.service",
        args,
        WatchOutcome(),
        _Group(),
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

    async def slow(*args: object, **kwargs: object) -> None:
        await anyio.sleep(30)

    monkeypatch.setattr(tail_cmd, "resolve_existing", resolve)
    monkeypatch.setattr(tail_cmd, "_stream", slow)
    monkeypatch.setattr(tail_cmd, "_watch", slow)


def _tail_args(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "lines": None,
        "follow": True,
        "until_exit": False,
        "grep": None,
        "timeout": 0.05,
        "json": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_tail_until_exit_timeout_is_not_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stall_tail(monkeypatch)
    code = anyio.run(tail_cmd.cmd_tail, None, _tail_args(until_exit=True))
    assert code == 124
    assert "timed out" in capsys.readouterr().err


def test_tail_grep_timeout_reports_no_match(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stall_tail(monkeypatch)
    code = anyio.run(tail_cmd.cmd_tail, None, _tail_args(grep="READY"))
    assert code == 1
    assert "timed out" in capsys.readouterr().err


def test_tail_plain_follow_timeout_stays_quiet(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A bounded plain follow printed what arrived; stopping there is the job.
    _stall_tail(monkeypatch)
    code = anyio.run(tail_cmd.cmd_tail, None, _tail_args())
    assert code == 0
    assert "timed out" in capsys.readouterr().err
