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
