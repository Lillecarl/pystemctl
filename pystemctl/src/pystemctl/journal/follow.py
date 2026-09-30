"""Following a unit's journal for a matching line.

Used by the watcher: it races a pattern match against the unit finishing, so a
log line can end the wait early without polling the journal.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

import anyio

from .formatting import format_entry
from .reader import entries, open_reader


@dataclass(slots=True)
class Followed:
    """One matching journal line, with the cursor needed to resume."""

    line: str
    cursor: str


async def follow_lines(
    *,
    system_units: Sequence[str] = (),
    user_units: Sequence[str] = (),
    pattern: str | None = None,
    mode: str = "cat",
    since_lines: int | None = None,
) -> AsyncIterator[str]:
    """Yield formatted lines from the matched units as they arrive.

    With ``pattern`` set only matching lines are yielded. The reader starts at
    the tail, so it sees output from the moment of the call onward, plus the
    last ``since_lines`` entries so already-written output is not missed.
    """
    compiled = re.compile(pattern) if pattern else None
    reader = open_reader(system_units=system_units, user_units=user_units)
    async for entry in entries(reader, tail=since_lines or 0, follow=True):
        line = format_entry(entry, mode)
        if compiled is None or compiled.search(line):
            yield line
