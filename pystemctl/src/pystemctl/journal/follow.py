"""Following a unit's journal for a matching line.

Used by the watcher: it races a pattern match against the unit finishing, so a
log line can end the wait early without polling the journal.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

from .formatting import format_entry
from .reader import entries, message_text, open_reader


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
    skip_notices: bool = True,
    follow: bool = True,
) -> AsyncIterator[str]:
    """Yield formatted lines from the matched units as they arrive.

    With ``pattern`` set only matching entries are yielded. The pattern is
    matched against the entry's MESSAGE, not the formatted output, so it means
    the same thing whatever ``mode`` is. The reader starts at the tail, so it
    sees output from the moment of the call onward, plus the last
    ``since_lines`` entries so already-written output is not missed. With
    ``follow`` off it replays and ends, for units already stopped.
    """
    compiled = re.compile(pattern) if pattern else None
    reader = open_reader(system_units=system_units, user_units=user_units)
    async for entry in entries(
        reader, tail=since_lines or 0, follow=follow, skip_notices=skip_notices
    ):
        if compiled is not None and not compiled.search(message_text(entry)):
            continue
        yield format_entry(entry, mode)
