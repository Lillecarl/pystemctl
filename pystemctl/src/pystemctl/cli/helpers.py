"""Small helpers shared by the command handlers."""

from __future__ import annotations

import datetime as dt
import enum
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import partial
from typing import Any

import anyio

from .. import journal as jr
from .. import systemd as sd
from ..bus import Bus, Scope
from ..errors import PystemctlError, UnitNotFoundError
from ..systemd import Unit
from ..systemd.jobs import Job
from ..systemd.tags import read_tags, session_id
from ..systemd.units import environment_of
from .args import BaseArgs, MultiTargetArgs, SingleTargetArgs, WatchArgs
from .output import emit_json, warn


class TargetHow(enum.Enum):
    """How a target resolved: named, matched by tag, or found in the journal."""

    EXPLICIT = "explicit"
    TAG = "tag"
    COLLECTED = "collected"


@dataclass(frozen=True)
class Target:
    """One unit to act on, and how it was chosen."""

    name: str
    how: TargetHow


def _note_others(tags: Sequence[str], chosen: Job, others: list[Job]) -> None:
    """Name the passed-over matches, so a surprising choice stays visible."""
    warn(
        f"{len(others) + 1} jobs match {', '.join(tags)}; "
        f"using the newest, {chosen.name} "
        f"(also: {', '.join(job.name for job in others)})"
    )


async def _collected_target(scope: Scope, tags: Sequence[str], missing: PystemctlError) -> Target:
    """Name a finished job from its journal entries, or re-raise.

    The manager unloads a finished transient unit, so the bus cannot resolve
    its tag anymore; the unit's own log lines outlive it and carry the tags.
    A job that logged nothing leaves no trace, and then the original miss
    stands: silence from the journal is not a unit.
    """
    name = None
    try:
        name = await jr.newest_unit_for_tags(tags, system=scope is Scope.SYSTEM)
    except PystemctlError:
        name = None
    if name is None:
        raise missing
    warn(f"{name} already finished and was collected; reading its journal")
    return Target(name, TargetHow.COLLECTED)


async def _tagged_target(
    bus: Bus, tags: Sequence[str], scope: Scope, session: str | None
) -> Target:
    """The newest job carrying every tag, falling back to its journal."""
    try:
        chosen, others = await sd.resolve(bus, tags=tags, session=session)
    except PystemctlError as missing:
        return await _collected_target(scope, tags, missing)
    if chosen is None:
        # Unreachable against the real manager: without a unit name resolve
        # either matches or raises. The checker cannot see that, and a None
        # here must fail loudly at the source rather than twenty lines on.
        raise PystemctlError("give a unit name or at least one --tag")
    if others:
        _note_others(tags, chosen, others)
    return Target(chosen.name, TargetHow.TAG)


async def resolve_one(bus: Bus, args: SingleTargetArgs) -> Target:
    """Return the unit the command should act on.

    A unit name is used as given. Tags select the newest matching job; when
    several matched, the others are named on stderr so a surprising choice is
    visible rather than silent.
    """
    if not args.tags:
        if args.unit:
            return Target(sd.normalize_unit_name(args.unit), TargetHow.EXPLICIT)
        raise PystemctlError("no unit or tag given")
    return await _tagged_target(bus, args.tags, args.scope, None)


async def resolve_many(bus: Bus, args: MultiTargetArgs) -> list[Target]:
    """Unit names from the positionals plus the newest job matching --tag.

    ``logs`` and ``status`` read any number of units, so tags resolve to one
    more target on the list rather than replacing it.
    """
    targets = [Target(sd.normalize_unit_name(raw), TargetHow.EXPLICIT) for raw in args.units]
    if args.tags:
        targets.append(await _tagged_target(bus, args.tags, args.scope, args.session))
    if not targets:
        raise PystemctlError("give a unit name or at least one --tag")
    return targets


async def resolve_existing(bus: Bus, args: SingleTargetArgs) -> tuple[Target, dict[str, Any]]:
    """Resolve a target and read its properties, failing if it is not loaded.

    Returns the target and its property map, so a caller does not fetch the
    same properties twice. A unit the journal remembers finished and was
    collected by the manager, which unloads successful transient units almost
    at once; saying only "not found" would hide that its output is still
    readable.
    """
    target = await resolve_one(bus, args)
    props = await sd.try_unit_properties(bus, target.name)
    if not props or props.get("LoadState") == "not-found":
        if await has_journal_trace(target.name, args.scope):
            raise PystemctlError(
                f"Unit {target.name} already finished and was collected; "
                f"see pystemctl logs {target.name}"
            )
        raise UnitNotFoundError(target.name)
    return target, props


def emit(args: BaseArgs, text: str | None, payload: Any) -> None:
    if args.json:
        emit_json(payload)
    elif text is not None:
        print(text)


def strip_separator(command: Sequence[str]) -> list[str]:
    command = list(command)
    if command and command[0] == "--":
        command = command[1:]
    return command


def parse_property(text: str) -> tuple[str, tuple[str, Any]]:
    """Split a ``NAME=VALUE`` or ``NAME:type=VALUE`` command-line property."""
    name, separator, value = text.partition("=")
    if not separator:
        raise PystemctlError(f"property must be NAME=VALUE: {text!r}")
    typename = "s"
    if ":" in name:
        name, _, typename = name.partition(":")
    return name, (typename, sd.coerce_property_value(typename, value))


def parse_environment(items: Sequence[str]) -> dict[str, str]:
    environment: dict[str, str] = {}
    for item in items:
        key, separator, value = item.partition("=")
        if not separator:
            raise PystemctlError(f"environment must be KEY=VALUE: {item!r}")
        environment[key] = value
    return environment


def tail_count(lines: int | None, follow: bool, since: dt.datetime | None) -> int | None:
    if lines is not None:
        return lines
    if since is not None and not follow:
        return None
    return 10


def unit_payload(unit: Unit) -> dict[str, Any]:
    return {
        "unit": unit.name,
        "description": unit.description,
        "load_state": unit.load_state,
        "active_state": unit.active_state,
        "sub_state": unit.sub_state,
        "path": unit.path,
    }


def unit_payload_from_props(name: str, props: dict[str, Any]) -> dict[str, Any]:
    return {
        "unit": name,
        "description": props.get("Description"),
        "load_state": props.get("LoadState"),
        "active_state": props.get("ActiveState"),
        "sub_state": props.get("SubState"),
        "path": props.get("FragmentPath"),
        "transient": bool(props.get("Transient")),
        "result": props.get("Result"),
        "main_pid": props.get("MainPID"),
    }


class NoTimeout:
    """A drop-in for ``anyio.move_on_after`` that never fires."""

    def __enter__(self) -> NoTimeout:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


@dataclass
class WatchOutcome:
    """What a watcher learns before it stops.

    ``matched`` is set when a pattern was found. ``props`` holds the unit
    properties read at the end, which carry the result and exit status.
    """

    matched: bool = False
    props: dict[str, Any] = field(default_factory=dict)


def unit_groups(units: Sequence[str], scope: Scope) -> tuple[list[str], list[str]]:
    """Split unit names into the (system, user) pair the journal reader wants."""
    if scope is Scope.SYSTEM:
        return list(units), []
    return [], list(units)


async def has_journal_trace(name: str, scope: Scope) -> bool:
    """True when the journal holds any line for a unit, notices included.

    A collected unit leaves its log lines behind, while a name that never ran
    leaves nothing. One entry decides, so this stays cheap enough for an
    error path.
    """
    system_units, user_units = unit_groups([name], scope)
    reader = jr.open_reader(system_units=system_units, user_units=user_units)
    async for _entry in jr.entries(reader, tail=1, skip_notices=False):
        return True
    return False


def unit_session(props: dict[str, Any]) -> str | None:
    """The agent session a unit was started from, if it recorded one."""
    _tags, session = read_tags(environment_of(props))
    return session


def note_foreign_session(name: str, props: dict[str, Any]) -> None:
    """Name the owning session when acting on another session's unit.

    Sessions attribute work, and a destructive command that crosses that line
    silently is how someone else's job gets stopped by mistake. One stderr
    line, no change to stdout, JSON, or the exit code.
    """
    session = unit_session(props)
    if session is not None and session != session_id():
        warn(f"{name} belongs to session {session}; acting anyway")


def timeout_note(timeout: float, name: str) -> None:
    """Say a bounded wait gave up, so silence never reads as success."""
    warn(f"timed out after {timeout:g}s waiting for {name}")


#: Exit code when a bounded wait gives up. The unit's own exit is unknown, so
#: this must differ from both success (0) and the unit's failure codes; it
#: matches ``timeout(1)``.
TIMEOUT_EXIT_CODE = 124


def exit_code_from(props: dict[str, Any]) -> int:
    """Map a stopped unit's properties to the shell exit code for its result.

    A unit killed by a signal, timed out, or that failed for another reason
    reports a result other than "success" but no exit-code status, so it maps
    to 1. Only a service's own non-zero exit carries its number.
    """
    result = props.get("Result")
    status = props.get("ExecMainStatus")
    if result == "exit-code" and isinstance(status, int) and status:
        return status
    return 0 if result in (None, "success") else 1


async def follow_matching(
    name: str,
    args: WatchArgs,
    outcome: WatchOutcome,
    group: anyio.abc.TaskGroup,
    *,
    replay: int,
    stop_on_match: bool,
    skip_notices: bool = True,
    live: bool = True,
) -> None:
    """Stream a unit's output into stdout, recording a pattern match.

    Shared by ``wait`` and ``tail``. With ``stop_on_match`` the first matching
    line ends the watch; otherwise every line is printed and only a match is
    recorded. The pattern is matched against each entry's MESSAGE, so --grep
    means the same thing whatever the output mode is. A set pattern matches
    the manager's lifecycle lines too, so waiting on an expected notice
    still works; without one they stay hidden. With ``live`` off the replay
    prints and the stream ends, for units already stopped.
    """
    system_units, user_units = unit_groups([name], args.scope)
    async for line in jr.follow_lines(
        system_units=system_units,
        user_units=user_units,
        pattern=args.grep,
        mode="json" if args.json else "cat",
        since_lines=replay,
        skip_notices=skip_notices,
        follow=live,
    ):
        print(line, flush=True)
        if args.grep:
            outcome.matched = True
            if stop_on_match:
                group.cancel_scope.cancel()
                return
    group.cancel_scope.cancel()


async def watch_unit(
    bus: Bus,
    name: str,
    args: WatchArgs,
    outcome: WatchOutcome,
    *,
    replay: int,
    stop_on_match: bool,
    skip_notices: bool,
    watch_finish: bool = True,
) -> None:
    """Race the unit finishing against its journal stream, in a group owned here.

    The stream prints output and records a pattern match; the finish side
    records the final properties. Whichever wins cancels the other, so a
    match ends the wait early and a stop ends the stream. An outer timeout
    still cancels the race from outside. Skip the finish side when the unit
    is already done: there is nothing to wait for, and the stream then ends
    after the replay instead of following a dead unit forever.
    """
    async with anyio.create_task_group() as group:
        group.start_soon(
            partial(
                follow_matching,
                name,
                args,
                outcome,
                group,
                replay=replay,
                stop_on_match=stop_on_match,
                skip_notices=skip_notices,
                live=watch_finish,
            )
        )
        if watch_finish:
            group.start_soon(_watch_finished, bus, name, outcome, group)


async def _watch_finished(
    bus: Bus, name: str, outcome: WatchOutcome, group: anyio.abc.TaskGroup
) -> None:
    outcome.props = await sd.wait_until_finished(bus, name)
    group.cancel_scope.cancel()
