from __future__ import annotations

import argparse
from collections.abc import Sequence
from functools import partial

import anyio
import pytest
from conftest import BUS

from pystemctl import journal as jr
from pystemctl.cli import helpers
from pystemctl.errors import PystemctlError
from pystemctl.journal import reader
from pystemctl.systemd.transient import TransientSpec, build_transient_properties


def _spec(**overrides: object) -> TransientSpec:
    values: dict[str, object] = {"name": "x.service", "argv": ["echo", "hi"]}
    values.update(overrides)
    return TransientSpec(**values)  # type: ignore[arg-type]


def _fields(spec: TransientSpec) -> dict[str, tuple[str, object]]:
    return {name: typed for name, typed in build_transient_properties(spec)}


def test_tags_ride_along_as_journal_fields() -> None:
    # The wire type is a(aay): whole FIELD=value strings, as systemd-run sends.
    assert _fields(_spec(tags=["a", "b"]))["LogExtraFields"] == (
        "aay",
        [b"PYSTEMCTL_TAG=a", b"PYSTEMCTL_TAG=b"],
    )


def test_no_tags_no_extra_fields() -> None:
    assert "LogExtraFields" not in _fields(_spec())


def test_unjournalable_tags_are_left_out() -> None:
    assert _fields(_spec(tags=["ok", "a\nb", "c\x00d"]))["LogExtraFields"] == (
        "aay",
        [b"PYSTEMCTL_TAG=ok"],
    )


class FakeReader:
    """Entries newest-first out of get_previous, like a tailed journal."""

    def __init__(self, log: list[dict[str, object]]) -> None:
        self.log = log

    def seek_tail(self) -> None:
        pass

    def get_previous(self) -> dict[str, object] | None:
        return self.log.pop() if self.log else None


def _reader_with(monkeypatch: pytest.MonkeyPatch, log: list[dict[str, object]]) -> list[object]:
    seen: list[object] = []

    def fake(**kwargs: object) -> FakeReader:
        seen.append(kwargs.get("tags"))
        return FakeReader(list(log))

    monkeypatch.setattr(reader, "open_reader", fake)
    return seen


def test_newest_tagged_unit_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    _reader_with(
        monkeypatch,
        [
            {"_SYSTEMD_USER_UNIT": "old.service"},
            {"MESSAGE": "no unit here"},
            {"_SYSTEMD_USER_UNIT": "new.service"},
        ],
    )
    assert anyio.run(jr.newest_unit_for_tags, ["t"]) == "new.service"


def test_manager_notice_subject_beats_sender_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The manager logs from init.scope; the job is named in USER_UNIT."""
    _reader_with(
        monkeypatch,
        [{"USER_UNIT": "job.service", "_SYSTEMD_USER_UNIT": "init.scope"}],
    )
    assert anyio.run(jr.newest_unit_for_tags, ["t"]) == "job.service"


def test_system_scope_reads_system_units(monkeypatch: pytest.MonkeyPatch) -> None:
    _reader_with(monkeypatch, [{"_SYSTEMD_UNIT": "sys.service"}])
    resolve = partial(jr.newest_unit_for_tags, ["t"], system=True)
    assert anyio.run(resolve) == "sys.service"


def test_no_tagged_entries_is_no_unit(monkeypatch: pytest.MonkeyPatch) -> None:
    _reader_with(monkeypatch, [{"MESSAGE": "unrelated"}])
    assert anyio.run(jr.newest_unit_for_tags, ["t"]) is None


def test_empty_tags_never_opens_a_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _reader_with(monkeypatch, [])
    assert anyio.run(jr.newest_unit_for_tags, []) is None
    assert seen == []


def test_tags_reach_the_reader_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _reader_with(monkeypatch, [])
    anyio.run(jr.newest_unit_for_tags, ["a", "b"])
    assert seen == [["a", "b"]]


def test_tag_matches_share_one_conjunction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Entries must carry every tag, so the matches form one AND group."""
    calls: list[tuple[str, ...]] = []

    class FakeReaderModule:
        def __init__(self, flags: int) -> None:
            pass

        def add_match(self, match: str) -> None:
            calls.append(("match", match))

        def add_disjunction(self) -> None:
            calls.append(("or",))

    class FakeJournal:
        LOCAL_ONLY = 0
        Reader = FakeReaderModule

    monkeypatch.setattr(reader, "_journal_module", lambda: FakeJournal())
    reader.open_reader(tags=["a", "b"])
    assert calls == [("match", "PYSTEMCTL_TAG=a"), ("match", "PYSTEMCTL_TAG=b")]


def _resolve_args(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {"units": [], "tags": [], "session": None}
    values.update(overrides)
    return argparse.Namespace(**values)


def test_resolve_units_falls_back_to_the_journal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def missing(bus: object, **_: object) -> object:
        raise PystemctlError("no job tagged t")

    async def found(tags: Sequence[str], **_: object) -> str | None:
        return "old.service"

    monkeypatch.setattr("pystemctl.systemd.resolve", missing)
    monkeypatch.setattr(jr, "newest_unit_for_tags", found)
    units = anyio.run(helpers.resolve_units, BUS, _resolve_args(tags=["t"]))
    assert units == ["old.service"]
    assert "collected" in capsys.readouterr().err


def test_resolve_units_keeps_the_original_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def missing(bus: object, **_: object) -> object:
        raise PystemctlError("no job tagged t")

    async def found(tags: Sequence[str], **_: object) -> str | None:
        return None

    monkeypatch.setattr("pystemctl.systemd.resolve", missing)
    monkeypatch.setattr(jr, "newest_unit_for_tags", found)
    with pytest.raises(PystemctlError, match="no job tagged"):
        anyio.run(helpers.resolve_units, BUS, _resolve_args(tags=["t"]))
