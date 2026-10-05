"""Argument parsers for pystemctl and pyjournalctl."""

from __future__ import annotations

import argparse
import os
from collections.abc import Awaitable, Callable, Iterable, Sequence

from .. import journal as jr
from ..bus import Bus, Scope
from . import commands

_Handler = Callable[[Bus, argparse.Namespace], Awaitable[int]]


def _profile_completer(**_: object) -> list[str]:
    from ..profiles import load_profiles

    try:
        return sorted(load_profiles())
    except Exception:
        return []


def _complete_from_bus(
    prefix: str,
    parsed_args: object,
    query: Callable[[Bus], Awaitable[Iterable[str]]],
) -> list[str]:
    """Run a bus query for completion; [] on any failure.

    Completion must never fail loudly. The manager may be unreachable, and
    a traceback on TAB is worse than no suggestions.
    """
    try:
        import anyio

        from ..bus import Scope, connect

        scope = getattr(parsed_args, "scope", None) or Scope.USER

        async def run() -> Iterable[str]:
            async with connect(scope) as bus:
                return await query(bus)

        names = anyio.run(run)
    except Exception:
        return []
    return sorted({name for name in names if name.startswith(prefix)})


def _unit_completer(
    prefix: str = "", parsed_args: object = None, **_: object
) -> list[str]:
    """Unit names from the relevant service manager."""
    from ..systemd.units import list_units

    async def query(bus: Bus) -> list[str]:
        return [unit.name for unit in await list_units(bus)]

    return _complete_from_bus(prefix, parsed_args, query)


def _unit_file_completer(
    prefix: str = "", parsed_args: object = None, **_: object
) -> list[str]:
    """Installed unit file names, for enable and disable."""
    from ..systemd.units import list_unit_files

    async def query(bus: Bus) -> list[str]:
        return [os.path.basename(path) for path, _state in await list_unit_files(bus)]

    return _complete_from_bus(prefix, parsed_args, query)


def _slice_completer(
    prefix: str = "", parsed_args: object = None, **_: object
) -> list[str]:
    """Slice names from the relevant service manager."""
    from ..systemd.units import list_units

    async def query(bus: Bus) -> list[str]:
        return [unit.name for unit in await list_units(bus) if unit.name.endswith(".slice")]

    return _complete_from_bus(prefix, parsed_args, query)


def _tags_completer(
    prefix: str = "", parsed_args: object = None, **_: object
) -> list[str]:
    """Tags carried by any job, whatever the session."""
    from ..systemd.jobs import collect_jobs

    async def query(bus: Bus) -> list[str]:
        jobs = await collect_jobs(bus, session=None, include_inactive=True)
        return [tag for job in jobs for tag in job.tags]

    return _complete_from_bus(prefix, parsed_args, query)


def _session_completer(
    prefix: str = "", parsed_args: object = None, **_: object
) -> list[str]:
    """Session ids carried by any job."""
    from ..systemd.jobs import collect_jobs

    async def query(bus: Bus) -> list[str]:
        jobs = await collect_jobs(bus, session=None, include_inactive=True)
        return [job.session for job in jobs if job.session]

    return _complete_from_bus(prefix, parsed_args, query)


def _show_property_completer(
    prefix: str = "", parsed_args: object = None, **_: object
) -> list[str]:
    """Property names of the unit being shown."""
    from .. import systemd as sd

    targets = getattr(parsed_args, "units", None) or []
    if not targets:
        return []

    async def query(bus: Bus) -> Iterable[str]:
        return await sd.unit_properties(bus, sd.normalize_unit_name(targets[0]))

    return _complete_from_bus(prefix, parsed_args, query)


def _env_completer(prefix: str = "", **_: object) -> list[str]:
    """Caller environment variable names, up to the '='."""
    key, separator, _value = prefix.partition("=")
    if separator:
        return []
    return sorted(name for name in os.environ if name.startswith(key))


def _executable_completer(prefix: str = "", parsed_args: object = None, **_: object) -> list[str]:
    """Executables on PATH for the command word; files after that."""
    if "/" in prefix:
        return []
    words = getattr(parsed_args, "command", None) or []
    if words:
        return []
    found: set[str] = set()
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        try:
            entries = os.listdir(directory)
        except OSError:
            continue
        for entry in entries:
            if not entry.startswith(prefix):
                continue
            path = os.path.join(directory, entry)
            if os.path.isfile(path) and os.access(path, os.X_OK):
                found.add(entry)
    return sorted(found)


_UNIT_TYPES = [
    "service",
    "socket",
    "device",
    "mount",
    "automount",
    "swap",
    "target",
    "path",
    "timer",
    "slice",
    "scope",
]

_ACTIVE_STATES = ["active", "inactive", "failed", "activating", "deactivating"]

_FILE_STATES = [
    "enabled",
    "enabled-runtime",
    "linked",
    "linked-runtime",
    "alias",
    "masked",
    "masked-runtime",
    "static",
    "disabled",
    "indirect",
    "generated",
    "transient",
]

_PRIORITIES = ["emerg", "alert", "crit", "err", "warning", "notice", "info", "debug"]

_SERVICE_PROPERTIES = [
    "CPUQuota",
    "CPUWeight",
    "Description",
    "Environment",
    "Group",
    "IOWeight",
    "KillMode",
    "LimitNOFILE",
    "LimitNPROC",
    "MemoryHigh",
    "MemoryLow",
    "MemoryMax",
    "Nice",
    "NoNewPrivileges",
    "PrivateTmp",
    "ProtectHome",
    "ProtectSystem",
    "RemainAfterExit",
    "Restart",
    "RestartSec",
    "RuntimeMaxSec",
    "Slice",
    "SuccessExitStatus",
    "SupplementaryGroups",
    "TasksMax",
    "TimeoutStartSec",
    "TimeoutStopSec",
    "User",
    "WorkingDirectory",
]


def _from_list(values: Sequence[str]) -> Callable[..., list[str]]:
    def complete(prefix: str = "", **_: object) -> list[str]:
        return [value for value in values if value.startswith(prefix)]

    complete.__name__ = f"complete_{len(values)}_static"
    return complete


_unit_type_completer = _from_list(_UNIT_TYPES)
_unit_state_completer = _from_list(_ACTIVE_STATES)
_unit_file_state_completer = _from_list(_FILE_STATES)
_priority_completer = _from_list(_PRIORITIES)
_service_property_completer = _from_list(_SERVICE_PROPERTIES)


def register_completers(parser: argparse.ArgumentParser) -> None:
    """Attach value completers that argcomplete resolves at completion time."""
    global_completers = {
        "profile": _profile_completer,
        "name": _profile_completer,
        "units": _unit_completer,
        "unit": _unit_completer,
        "system_units": _unit_completer,
        "user_units": _unit_completer,
        "tags": _tags_completer,
        "session": _session_completer,
        "setenv": _env_completer,
        "property": _service_property_completer,
        "properties": _show_property_completer,
        "slice_name": _slice_completer,
        "priority": _priority_completer,
        "command": _executable_completer,
    }
    # Dests shared by unrelated options need per-command precision: run's
    # --type takes choices that argcomplete already completes, while list's
    # --type is free text, and enable wants files where the rest want units.
    per_command = {
        "enable": {"units": _unit_file_completer},
        "disable": {"units": _unit_file_completer},
        "list": {"type": _unit_type_completer, "state": _unit_state_completer},
        "list-unit-files": {
            "type": _unit_type_completer,
            "state": _unit_file_state_completer,
        },
    }
    targets: list[tuple[str, argparse.ArgumentParser]] = [("", parser)]
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            targets.extend(action.choices.items())
    for name, target in targets:
        overrides = per_command.get(name, {})
        for subaction in target._actions:
            completer = overrides.get(subaction.dest, global_completers.get(subaction.dest))
            if completer is not None:
                subaction.completer = completer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pystemctl",
        description="Inspect and control systemd units, and run ephemeral user units.",
        epilog=(
            "ephemeral jobs: run, jobs, wait, tail. "
            "wait reports the outcome, tail streams the output until the unit stops, "
            "logs reads past lines. "
            "unit control: list, start, stop, restart, reload, rm, enable, disable, "
            "is-active, is-failed, is-enabled, cat, show, daemon-reload."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = _add(
        subparsers,
        "run",
        commands.cmd_run,
        "start a command as an ephemeral unit",
        option_groups=[_job_filter_options()],
    )
    run.add_argument("--unit", metavar="NAME", help="unit name (default: generated)")
    run.add_argument(
        "--profile",
        metavar="NAME",
        help="load defaults from a named profile before the command line",
    )
    run.add_argument("--description", "-d", metavar="TEXT")
    run.add_argument("--working-directory", "-D", metavar="DIR")
    run.add_argument("--setenv", "-E", action="append", default=[], metavar="KEY=VALUE")
    run.add_argument(
        "--clean",
        action="store_true",
        help="start with an empty environment instead of inheriting the caller's",
    )
    run.add_argument("--property", "-P", action="append", default=[], metavar="NAME=VALUE")
    run.add_argument("--type", default="simple", choices=["simple", "exec", "oneshot", "idle"])
    run.add_argument("--remain-after-exit", action="store_true")
    collect = run.add_mutually_exclusive_group()
    collect.add_argument(
        "--collect",
        dest="collect",
        action="store_true",
        default=None,
        help="unload the unit once it stops (default unless a tag is set)",
    )
    collect.add_argument(
        "--no-collect",
        dest="collect",
        action="store_false",
        help="keep the unit after it exits, so its result stays readable",
    )
    run.add_argument("--replace", action="store_true", help="replace an existing unit of this name")
    run.add_argument("--no-block", action="store_true", help="do not wait for the start job")
    run.add_argument(
        "--wait",
        action="store_true",
        help="wait until the command exits, streaming its output",
    )
    run.add_argument("--runtime-max", type=float, metavar="SECONDS")
    run.add_argument("--nice", type=int)
    run.add_argument("--slice", dest="slice_name", metavar="SLICE")
    run.add_argument("--shell", action="store_true", help="run through sh -c")
    run.add_argument("command", nargs=argparse.REMAINDER, metavar="COMMAND ...")

    units = _add(subparsers, "list", commands.cmd_list, "list units", aliases=["ls", "units"])
    units.add_argument("--all", "-a", action="store_true", help="include inactive units")
    units.add_argument("--type", "-t", metavar="TYPE", help="filter by unit type")
    units.add_argument("--state", metavar="STATE", help="filter by active or sub state")
    units.add_argument("--ephemeral", action="store_true", help="only transient units")

    files = _add(
        subparsers, "list-unit-files", commands.cmd_list_unit_files, "list installed unit files"
    )
    files.add_argument("--type", "-t", metavar="TYPE")
    files.add_argument("--state", metavar="STATE")

    status = _add(
        subparsers,
        "status",
        commands.cmd_status,
        "show unit status",
        option_groups=[
            _unit_positional(required=False),
            _job_filter_options(),
            _replay_option(10),
        ],
    )
    status.add_argument("--no-journal", action="store_true")

    for name, handler, help_text in (
        ("start", commands.cmd_start, "start units"),
        ("stop", commands.cmd_stop, "stop units"),
        ("restart", commands.cmd_restart, "restart units"),
        ("reload", commands.cmd_reload, "reload units"),
        ("rm", commands.cmd_rm, "stop and forget units"),
        ("is-active", commands.cmd_is_active, "check whether units are active"),
        ("is-failed", commands.cmd_is_failed, "check whether units have failed"),
        ("is-enabled", commands.cmd_is_enabled, "check whether units are enabled"),
        ("enable", commands.cmd_enable, "enable unit files"),
        ("disable", commands.cmd_disable, "disable unit files"),
        ("cat", commands.cmd_cat, "show unit file contents"),
    ):
        _add(subparsers, name, handler, help_text, option_groups=[_unit_positional()])

    show = _add(
        subparsers,
        "show",
        commands.cmd_show,
        "dump unit properties",
        option_groups=[_unit_positional(required=False)],
    )
    show.add_argument(
        "-P",
        "--property",
        dest="properties",
        action="append",
        metavar="NAME",
        help="print only this property; repeat for several",
    )

    _add(subparsers, "daemon-reload", commands.cmd_daemon_reload, "reload unit files")

    _add(
        subparsers,
        "logs",
        commands.cmd_logs,
        "show journal entries for units (tail follows live output instead)",
        option_groups=[
            _unit_positional(required=False),
            _job_filter_options(),
            _journal_options(),
            _follow_option(),
            _replay_option(),
        ],
    )

    jobs = _add(
        subparsers,
        "jobs",
        commands.cmd_jobs,
        "list ephemeral jobs, by tag or session",
        option_groups=[_job_filter_options()],
    )
    jobs.add_argument("--any-session", action="store_true", help="list jobs from every session")
    jobs.add_argument("--all", "-a", action="store_true", help="include finished jobs")
    jobs.add_argument(
        "--all-transient",
        action="store_true",
        help="include transient units that are not pystemctl jobs",
    )
    jobs.add_argument(
        "--follow",
        "-f",
        action="store_true",
        help="emit a line whenever a job appears, changes, or goes away",
    )

    _add(
        subparsers,
        "wait",
        commands.cmd_wait,
        "wait for a unit to finish or log a match (tail streams the output)",
        option_groups=[_watch_options(), _replay_option(200), _target_selector()],
    )

    tail = _add(
        subparsers,
        "tail",
        commands.cmd_tail,
        "follow a unit's output until it stops or a line matches "
        "(wait only reports the outcome; logs reads past lines)",
        option_groups=[
            _replay_option(200),
            _watch_options(),
            _follow_option(),
            _target_selector(),
        ],
    )
    tail.add_argument(
        "--until-exit",
        action="store_true",
        help="keep following until the unit stops, then return its exit status",
    )

    profile = _add(subparsers, "profile", commands.cmd_profile, "inspect command profiles")
    profile.add_argument(
        "action", nargs="?", choices=["list", "show", "path"], default="list"
    )
    profile.add_argument("name", nargs="?", metavar="NAME")

    return parser


def build_journal_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyjournalctl",
        description="Query the systemd journal.",
        parents=[_replay_option(), _journal_options(), _follow_option()],
    )
    parser.add_argument(
        "--no-pager", action="store_true", help="accepted for journalctl compatibility"
    )
    parser.add_argument(
        "-u", "--unit", dest="system_units", action="append", default=[], metavar="UNIT"
    )
    parser.add_argument(
        "--user-unit", dest="user_units", action="append", default=[], metavar="UNIT"
    )
    parser.add_argument("--json", action="store_true")
    return parser


def _scope_options() -> argparse.ArgumentParser:
    """The ``--user``/``--system`` choice, shared by every command."""
    parser = argparse.ArgumentParser(add_help=False)
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--user",
        dest="scope",
        action="store_const",
        const=Scope.USER,
        help="use the calling user's service manager (default)",
    )
    group.add_argument(
        "--system",
        dest="scope",
        action="store_const",
        const=Scope.SYSTEM,
        help="use the system service manager",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.set_defaults(scope=Scope.USER)
    return parser


def _unit_positional(*, required: bool = True) -> argparse.ArgumentParser:
    """One or more unit names as positional arguments."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("units", nargs="+" if required else "*", metavar="UNIT")
    return parser


def _target_selector() -> argparse.ArgumentParser:
    """A single unit, by name or by tag. The two are mutually exclusive."""
    parser = argparse.ArgumentParser(add_help=False)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("unit", nargs="?", metavar="UNIT")
    group.add_argument(
        "--tag",
        "-T",
        dest="tags",
        action="append",
        metavar="TAG",
        help="select the newest job carrying every given tag",
    )
    return parser


def _replay_option(default: int | None = None) -> argparse.ArgumentParser:
    """The ``-n/--lines`` replay count, shared by every command that reads logs."""
    parser = argparse.ArgumentParser(add_help=False)
    help_text = "how many recent lines to read"
    if default is not None:
        help_text += f" (default: {default})"
    parser.add_argument("-n", "--lines", type=int, default=default, metavar="N", help=help_text)
    return parser


def _watch_options() -> argparse.ArgumentParser:
    """The timeout and pattern that turn a log reader into a watcher."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--timeout", type=float, metavar="SECONDS")
    parser.add_argument(
        "--grep", metavar="PATTERN", help="select matching lines; return early on a match"
    )
    return parser


def _follow_option() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "-f", "--follow", action="store_true", help="keep printing new lines as they arrive"
    )
    return parser


def _journal_options() -> argparse.ArgumentParser:
    """The shared timestamp, priority, boot and output options."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--since")
    parser.add_argument("--until")
    parser.add_argument("-p", "--priority", metavar="LEVEL")
    parser.add_argument("-b", "--boot", nargs="?", const=True, default=None, metavar="ID")
    parser.add_argument("-o", "--output", default="short", choices=jr.OUTPUT_MODES)
    return parser


def _job_filter_options() -> argparse.ArgumentParser:
    """The tag and session filters shared by ``run`` and ``jobs``."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--tag",
        "-T",
        dest="tags",
        action="append",
        default=[],
        metavar="TAG",
        help="tag a job, or select the newest job carrying every given tag",
    )
    parser.add_argument("--session", metavar="ID")
    return parser


def _add(
    subparsers: argparse._SubParsersAction,
    name: str,
    handler: _Handler,
    help_text: str,
    *,
    aliases: Sequence[str] = (),
    option_groups: Sequence[argparse.ArgumentParser] = (),
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        name,
        parents=[_scope_options(), *option_groups],
        aliases=list(aliases),
        help=help_text,
        description=help_text,
    )
    parser.set_defaults(handler=handler)
    return parser
