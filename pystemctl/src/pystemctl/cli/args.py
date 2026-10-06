"""Typed per-command arguments.

Every handler declares what it takes as a frozen dataclass instead of
threading argparse.Namespace through with getattr-with-default lookups.
Field defaults mirror the parser defaults, so a test can build a partial
shape and only the fields under test need values. ``from_namespace``
converts a real parse with direct attribute access: a missing attribute
raises instead of silently defaulting, and ``test_parser`` pins that every
attribute the parser sets has a field waiting for it.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field

from ..bus import Scope


@dataclass(frozen=True)
class BaseArgs:
    """The ``--user``/``--system`` choice and ``--json``, on every command."""

    scope: Scope = Scope.USER
    json: bool = False

    @classmethod
    def from_namespace(cls, ns: argparse.Namespace) -> BaseArgs:
        return cls(scope=ns.scope, json=ns.json)


@dataclass(frozen=True)
class UnitsArgs(BaseArgs):
    """Commands taking unit names as positionals."""

    units: list[str] = field(default_factory=list)

    @classmethod
    def from_namespace(cls, ns: argparse.Namespace) -> UnitsArgs:
        return cls(scope=ns.scope, json=ns.json, units=list(ns.units))


@dataclass(frozen=True)
class ShowArgs(BaseArgs):
    units: list[str] = field(default_factory=list)
    properties: list[str] | None = None

    @classmethod
    def from_namespace(cls, ns: argparse.Namespace) -> ShowArgs:
        # systemctl spells several properties -P A,B; split commas there too.
        properties: list[str] | None = None
        if ns.properties:
            properties = [name for entry in ns.properties for name in entry.split(",") if name]
        return cls(scope=ns.scope, json=ns.json, units=list(ns.units), properties=properties)


@dataclass(frozen=True)
class SingleTargetArgs(BaseArgs):
    """Commands acting on one unit, by name or by tag."""

    unit: str | None = None
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_namespace(cls, ns: argparse.Namespace) -> SingleTargetArgs:
        return cls(scope=ns.scope, json=ns.json, unit=ns.unit, tags=list(ns.tags or []))


@dataclass(frozen=True)
class MultiTargetArgs(BaseArgs):
    """Commands reading any number of units, by name or by tag."""

    units: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    session: str | None = None

    @classmethod
    def from_namespace(cls, ns: argparse.Namespace) -> MultiTargetArgs:
        return cls(
            scope=ns.scope,
            json=ns.json,
            units=list(ns.units),
            tags=list(ns.tags),
            session=ns.session,
        )


@dataclass(frozen=True)
class WatchArgs(SingleTargetArgs):
    """The pattern a watcher selects lines with."""

    grep: str | None = None

    @classmethod
    def from_namespace(cls, ns: argparse.Namespace) -> WatchArgs:
        return cls(
            scope=ns.scope,
            json=ns.json,
            unit=ns.unit,
            tags=list(ns.tags or []),
            grep=ns.grep,
        )


@dataclass(frozen=True)
class RunArgs(BaseArgs):
    unit: str | None = None
    profile: str | None = None
    description: str | None = None
    working_directory: str | None = None
    setenv: list[str] = field(default_factory=list)
    clean: bool = False
    property: list[str] = field(default_factory=list)
    type: str | None = None
    remain_after_exit: bool = False
    collect: bool | None = None
    replace: bool = False
    no_block: bool = False
    wait: bool = False
    runtime_max: float | None = None
    nice: int | None = None
    slice_name: str | None = None
    shell: bool = False
    command: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    session: str | None = None

    @classmethod
    def from_namespace(cls, ns: argparse.Namespace) -> RunArgs:
        return cls(
            scope=ns.scope,
            json=ns.json,
            unit=ns.unit,
            profile=ns.profile,
            description=ns.description,
            working_directory=ns.working_directory,
            setenv=list(ns.setenv),
            clean=ns.clean,
            property=list(ns.property),
            type=ns.type,
            remain_after_exit=ns.remain_after_exit,
            collect=ns.collect,
            replace=ns.replace,
            no_block=ns.no_block,
            wait=ns.wait,
            runtime_max=ns.runtime_max,
            nice=ns.nice,
            slice_name=ns.slice_name,
            shell=ns.shell,
            command=list(ns.command),
            tags=list(ns.tags),
            session=ns.session,
        )


@dataclass(frozen=True)
class ListArgs(BaseArgs):
    all: bool = False
    type: str | None = None
    state: str | None = None
    ephemeral: bool = False

    @classmethod
    def from_namespace(cls, ns: argparse.Namespace) -> ListArgs:
        return cls(
            scope=ns.scope,
            json=ns.json,
            all=ns.all,
            type=ns.type,
            state=ns.state,
            ephemeral=ns.ephemeral,
        )


@dataclass(frozen=True)
class ListFilesArgs(BaseArgs):
    type: str | None = None
    state: str | None = None

    @classmethod
    def from_namespace(cls, ns: argparse.Namespace) -> ListFilesArgs:
        return cls(scope=ns.scope, json=ns.json, type=ns.type, state=ns.state)


@dataclass(frozen=True)
class StatusArgs(MultiTargetArgs):
    lines: int = 10
    no_journal: bool = False

    @classmethod
    def from_namespace(cls, ns: argparse.Namespace) -> StatusArgs:
        return cls(
            scope=ns.scope,
            json=ns.json,
            units=list(ns.units),
            tags=list(ns.tags),
            session=ns.session,
            lines=ns.lines,
            no_journal=ns.no_journal,
        )


@dataclass(frozen=True)
class LogsArgs(MultiTargetArgs):
    since: str | None = None
    until: str | None = None
    priority: str | None = None
    boot: bool | str | None = None
    output: str = "short"
    lines: int | None = None
    follow: bool = False

    @classmethod
    def from_namespace(cls, ns: argparse.Namespace) -> LogsArgs:
        return cls(
            scope=ns.scope,
            json=ns.json,
            units=list(ns.units),
            tags=list(ns.tags),
            session=ns.session,
            since=ns.since,
            until=ns.until,
            priority=ns.priority,
            boot=ns.boot,
            output=ns.output,
            lines=ns.lines,
            follow=ns.follow,
        )


@dataclass(frozen=True)
class JobsArgs(BaseArgs):
    tags: list[str] = field(default_factory=list)
    session: str | None = None
    any_session: bool = False
    all: bool = False
    all_transient: bool = False
    follow: bool = False

    @classmethod
    def from_namespace(cls, ns: argparse.Namespace) -> JobsArgs:
        return cls(
            scope=ns.scope,
            json=ns.json,
            tags=list(ns.tags),
            session=ns.session,
            any_session=ns.any_session,
            all=ns.all,
            all_transient=ns.all_transient,
            follow=ns.follow,
        )


@dataclass(frozen=True)
class WaitArgs(WatchArgs):
    timeout: float | None = None
    lines: int | None = 200

    @classmethod
    def from_namespace(cls, ns: argparse.Namespace) -> WaitArgs:
        return cls(
            scope=ns.scope,
            json=ns.json,
            unit=ns.unit,
            tags=list(ns.tags or []),
            grep=ns.grep,
            timeout=ns.timeout,
            lines=ns.lines,
        )


@dataclass(frozen=True)
class TailArgs(WatchArgs):
    lines: int | None = 200
    timeout: float | None = None
    follow: bool = False
    until_exit: bool = False

    @classmethod
    def from_namespace(cls, ns: argparse.Namespace) -> TailArgs:
        return cls(
            scope=ns.scope,
            json=ns.json,
            unit=ns.unit,
            tags=list(ns.tags or []),
            grep=ns.grep,
            lines=ns.lines,
            timeout=ns.timeout,
            follow=ns.follow,
            until_exit=ns.until_exit,
        )


@dataclass(frozen=True)
class ProfileArgs(BaseArgs):
    action: str = "list"
    name: str | None = None

    @classmethod
    def from_namespace(cls, ns: argparse.Namespace) -> ProfileArgs:
        return cls(scope=ns.scope, json=ns.json, action=ns.action, name=ns.name)


@dataclass(frozen=True)
class JournalArgs:
    """pyjournalctl takes no scope; the reader splits units itself."""

    system_units: list[str] = field(default_factory=list)
    user_units: list[str] = field(default_factory=list)
    since: str | None = None
    until: str | None = None
    priority: str | None = None
    lines: int | None = None
    follow: bool = False
    boot: bool | str | None = None
    json: bool = False
    output: str = "short"
    no_pager: bool = False

    @classmethod
    def from_namespace(cls, ns: argparse.Namespace) -> JournalArgs:
        return cls(
            system_units=list(ns.system_units),
            user_units=list(ns.user_units),
            since=ns.since,
            until=ns.until,
            priority=ns.priority,
            lines=ns.lines,
            follow=ns.follow,
            boot=ns.boot,
            json=ns.json,
            output=ns.output,
            no_pager=ns.no_pager,
        )
