"""Argument parsers for pystemctl and pyjournalctl."""

from __future__ import annotations

import argparse
from collections.abc import Awaitable, Callable, Sequence

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


def register_completers(parser: argparse.ArgumentParser) -> None:
    """Attach value completers that argcomplete resolves at completion time."""
    completers = {"profile": _profile_completer}
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        for subparser in action.choices.values():
            for subaction in subparser._actions:
                completer = completers.get(subaction.dest)
                if completer is not None:
                    subaction.completer = completer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pystemctl",
        description="Inspect and control systemd units, and run ephemeral user units.",
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
    run.add_argument("--wait", action="store_true", help="wait until the command exits")
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
        option_groups=[_unit_positional(), _replay_option(10)],
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
        "show journal entries for units",
        option_groups=[
            _unit_positional(),
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
        "--follow",
        "-f",
        action="store_true",
        help="emit a line whenever a job appears, changes, or goes away",
    )

    _add(
        subparsers,
        "wait",
        commands.cmd_wait,
        "wait for a unit to finish or log a match",
        option_groups=[_watch_options(), _replay_option(200), _target_selector()],
    )

    tail = _add(
        subparsers,
        "tail",
        commands.cmd_tail,
        "follow a unit's output until it stops or a line matches",
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
