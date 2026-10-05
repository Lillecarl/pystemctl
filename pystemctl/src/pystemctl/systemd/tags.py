"""Tags carried on a unit as reserved environment variables.

systemd has no server-side index on arbitrary metadata, so tags travel in the
unit's ``Environment=``. The unit's environment is readable over D-Bus without
special privilege and survives a manager restart, which an external index does
not. A query reads the candidate units' environment and filters locally.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence
from typing import Final

TAGS_ENV: Final = "PYSTEMCTL_TAGS"
SESSION_ENV: Final = "PYSTEMCTL_SESSION"
RESERVED: Final = (TAGS_ENV, SESSION_ENV)

# Journal field carrying one tag per entry, so a finished job stays findable
# after the manager unloads its unit. The bus stays authoritative; the journal
# is only a fallback for units that are already gone.
TAG_FIELD: Final = "PYSTEMCTL_TAG"

SESSION_ID_LENGTH: Final = 12


def session_id() -> str:
    """Return the invoking opencode session, or a random one.

    An agent process usually inherits nothing that names its session, so the
    session id is taken from the environment when present and generated
    otherwise. ``run`` records it; other commands read it back.
    """
    for name in ("OPENCODE_SESSION_ID", "OCAHUB_SESSION", "OC_SESSION"):
        value = os.environ.get(name)
        if value:
            return value
    return os.urandom(SESSION_ID_LENGTH // 2).hex()


def tags_to_environment(tags: Iterable[str]) -> str:
    """Serialise tags into the single environment value the unit will hold."""
    seen: dict[str, None] = {}
    for tag in tags:
        cleaned = tag.strip()
        if cleaned:
            seen.setdefault(cleaned, None)
    return ",".join(seen)


def environment_to_tags(value: str) -> list[str]:
    return [tag for tag in (part.strip() for part in value.split(",")) if tag]


def read_tags(environment: Mapping[str, str]) -> tuple[list[str], str | None]:
    """Extract ``(tags, session)`` from a unit's environment mapping."""
    tags = environment_to_tags(environment.get(TAGS_ENV, ""))
    session = environment.get(SESSION_ENV) or None
    return tags, session


def matches(
    environment: Mapping[str, str],
    *,
    required_tags: Sequence[str] = (),
    session: str | None = None,
) -> bool:
    """True when the unit's environment satisfies every requested filter."""
    tags, unit_session = read_tags(environment)
    if session is not None and unit_session != session:
        return False
    return all(tag in tags for tag in required_tags)
