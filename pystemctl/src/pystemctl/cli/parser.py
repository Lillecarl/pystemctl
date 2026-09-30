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
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        for subparser in action.choices.values():
            for subaction in subparser._actions:
                if subaction.dest == "profile":
                    subaction.completer = _profile_completer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pystemctl",
        description="Inspect and control systemd units, and run ephemeral user units.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = _add(subparsers, "run", commands.cmd_run, "start a command as an ephemeral unit")
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
        "--tag",
        "-T",
        dest="tags",
        action="append",
        default=[],
        metavar="TAG",
        help="tag the job; query it back with 'pystemctl jobs --tag'",
    )
    run.add_argument(
        "--session",
        metavar="ID",
        help="session to record the job under (default: this session)",
    )
    run.add_argument("--property", "-P", action="append", default=[], metavar="NAME=VALUE")
    run.add_argument("--type", default="simple", choices=["simple", "exec", "oneshot", "idle"])
    run.add_argument("--remain-after-exit", action="store_true")
    run.add_argument("--no-collect", action="store_true", help="keep the unit after it exits")
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

    status = _add(subparsers, "status", commands.cmd_status, "show unit status")
    status.add_argument("units", nargs="+", metavar="UNIT")
    status.add_argument("-n", "--lines", type=int, default=10, metavar="N")
    status.add_argument("--no-journal", action="store_true")

    for name, handler, help_text in (
        ("start", commands.cmd_start, "start units"),
        ("stop", commands.cmd_stop, "stop units"),
        ("restart", commands.cmd_restart, "restart units"),
        ("reload", commands.cmd_reload, "reload units"),
        ("rm", commands.cmd_rm, "stop and forget units"),
    ):
        command = _add(subparsers, name, handler, help_text)
        command.add_argument("units", nargs="+", metavar="UNIT")

    active = _add(subparsers, "is-active", commands.cmd_is_active, "check whether units are active")
    active.add_argument("units", nargs="+", metavar="UNIT")

    failed = _add(subparsers, "is-failed", commands.cmd_is_failed, "check whether units have failed")
    failed.add_argument("units", nargs="+", metavar="UNIT")

    enabled = _add(
        subparsers, "is-enabled", commands.cmd_is_enabled, "check whether units are enabled"
    )
    enabled.add_argument("units", nargs="+", metavar="UNIT")

    enable = _add(subparsers, "enable", commands.cmd_enable, "enable unit files")
    enable.add_argument("units", nargs="+", metavar="UNIT")

    disable = _add(subparsers, "disable", commands.cmd_disable, "disable unit files")
    disable.add_argument("units", nargs="+", metavar="UNIT")

    cat = _add(subparsers, "cat", commands.cmd_cat, "show unit file contents")
    cat.add_argument("units", nargs="+", metavar="UNIT")

    show = _add(subparsers, "show", commands.cmd_show, "dump unit properties")
    show.add_argument("units", nargs="*", metavar="UNIT")

    _add(subparsers, "daemon-reload", commands.cmd_daemon_reload, "reload unit files")

    logs = _add(subparsers, "logs", commands.cmd_logs, "show journal entries for units")
    logs.add_argument("units", nargs="+", metavar="UNIT")
    add_journal_options(logs)

    jobs = _add(subparsers, "jobs", commands.cmd_jobs, "list ephemeral jobs, by tag or session")
    jobs.add_argument("--tag", "-T", dest="tags", action="append", default=[], metavar="TAG")
    jobs.add_argument("--session", metavar="ID", help="session to list (default: this session)")
    jobs.add_argument(
        "--any-session", action="store_true", help="list jobs from every session"
    )
    jobs.add_argument("--all", "-a", action="store_true", help="include finished jobs")

    wait = _add(subparsers, "wait", commands.cmd_wait, "wait for a unit to finish or log a match")
    wait.add_argument("unit", metavar="UNIT")
    wait.add_argument("--timeout", type=float, metavar="SECONDS")
    wait.add_argument("--grep", metavar="PATTERN", help="return early when a log line matches")
    wait.add_argument(
        "-n", "--lines", type=int, default=0, metavar="N", help="replay N lines before following"
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
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "-u", "--unit", dest="system_units", action="append", default=[], metavar="UNIT"
    )
    parser.add_argument(
        "--user-unit", dest="user_units", action="append", default=[], metavar="UNIT"
    )
    add_journal_options(parser)
    return parser


def add_journal_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--no-pager", action="store_true", help="accepted for journalctl compatibility"
    )
    parser.add_argument("-n", "--lines", type=int, default=None, metavar="N")
    parser.add_argument("-f", "--follow", action="store_true")
    parser.add_argument("--since")
    parser.add_argument("--until")
    parser.add_argument("-p", "--priority", metavar="LEVEL")
    parser.add_argument("-b", "--boot", nargs="?", const=True, default=None, metavar="ID")
    parser.add_argument("-o", "--output", default="short", choices=jr.OUTPUT_MODES)


def _add(
    subparsers: argparse._SubParsersAction,
    name: str,
    handler: _Handler,
    help_text: str,
    aliases: Sequence[str] = (),
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        name,
        parents=[_common_options()],
        aliases=list(aliases),
        help=help_text,
        description=help_text,
    )
    parser.set_defaults(handler=handler)
    return parser


def _common_options() -> argparse.ArgumentParser:
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
