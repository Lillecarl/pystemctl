"""Following must resume from the last replayed entry, not the tail.

The journal reader replays a tail of recent entries, then follows. If the
follow step seeks to the tail again, every entry written between the replay
and the follow attaching is skipped -- a gap the caller never sees.
"""

from __future__ import annotations

from functools import partial

import anyio

from pystemctl.journal.reader import entries

APPEND = 1  # systemd.journal.APPEND; INVALIDATE is 2


class FakeReader:
    """Enough of journal.Reader to drive entries(), recording the seeks."""

    def __init__(self, log: list[dict[str, object]]) -> None:
        self.log = log
        self.position = 0
        self.seeks: list[tuple[str, object]] = []
        self.appends: list[dict[str, object]] = []

    def seek_tail(self) -> None:
        self.seeks.append(("tail", None))
        self.position = len(self.log)

    def seek_head(self) -> None:
        self.seeks.append(("head", None))
        self.position = 0

    def seek_cursor(self, cursor: str) -> None:
        self.seeks.append(("cursor", cursor))
        for index, entry in enumerate(self.log):
            if entry["__CURSOR"] == cursor:
                self.position = index
                return
        raise AssertionError(f"unknown cursor {cursor!r}")

    def get_previous(self) -> dict[str, object] | None:
        self.position = max(0, self.position - 1)
        return self.log[self.position] if self.position < len(self.log) else None

    def get_next(self) -> dict[str, object] | None:
        if self.position >= len(self.log):
            return None
        entry = self.log[self.position]
        self.position += 1
        return entry

    def wait(self, timeout: float) -> int:
        if self.appends:
            self.log.extend(self.appends)
            self.appends = []
            return APPEND
        return 0


def _entry(index: int) -> dict[str, object]:
    return {"__CURSOR": f"c{index}", "__REALTIME_TIMESTAMP": index, "MESSAGE": f"L{index}"}


async def _drain(
    reader: FakeReader, *, budget: float = 0.05, **kwargs: object
) -> list[dict[str, object]]:
    """Collect entries until the follow loop goes quiet, then stop.

    A follow reader never returns on its own, so the budget bounds the test.
    """
    seen: list[dict[str, object]] = []

    async def collect(group: anyio.abc.TaskGroup) -> None:
        async for entry in entries(reader, **kwargs):  # type: ignore[arg-type]
            seen.append(entry)
        group.cancel_scope.cancel()

    with anyio.move_on_after(budget):
        async with anyio.create_task_group() as group:
            group.start_soon(collect, group)
    return seen


def test_follow_resumes_from_the_last_replayed_cursor() -> None:
    log = [_entry(index) for index in range(10)]
    reader = FakeReader(log)
    # Three entries arrive after the replay but before the follow loop runs;
    # they sit exactly in the window a re-seek to the tail would lose.
    reader.appends = [_entry(10), _entry(11), _entry(12)]

    seen = anyio.run(partial(_drain, reader, tail=2, follow=True))

    kinds = [kind for kind, _ in reader.seeks]
    assert "cursor" in kinds, kinds
    # The cursor is the last replayed entry (index 9), not the tail.
    cursor_seek = next(value for kind, value in reader.seeks if kind == "cursor")
    assert cursor_seek == "c9"
    messages = [entry["MESSAGE"] for entry in seen]
    assert messages == ["L8", "L9", "L10", "L11", "L12"]


def test_follow_without_a_cursor_falls_back_to_the_tail() -> None:
    # An empty replay leaves no cursor, so the tail fallback is used; entries
    # arriving after that are still followed.
    reader = FakeReader([])
    reader.appends = [_entry(0)]

    seen = anyio.run(partial(_drain, reader, tail=5, follow=True))

    assert [entry["MESSAGE"] for entry in seen] == ["L0"]
    assert ("tail", None) in reader.seeks
    assert "cursor" not in [kind for kind, _ in reader.seeks]


def test_replay_without_follow_does_not_seek_a_cursor() -> None:
    reader = FakeReader([_entry(index) for index in range(5)])

    seen = anyio.run(partial(_drain, reader, tail=2, follow=False))

    assert [entry["MESSAGE"] for entry in seen] == ["L3", "L4"]
    assert reader.seeks == [("tail", None)]


def test_head_path_follow_resumes_from_the_last_cursor() -> None:
    reader = FakeReader([_entry(index) for index in range(3)])
    reader.appends = [_entry(3)]

    seen = anyio.run(partial(_drain, reader, follow=True))

    assert "cursor" in [kind for kind, _ in reader.seeks]
    assert [entry["MESSAGE"] for entry in seen] == ["L0", "L1", "L2", "L3"]
