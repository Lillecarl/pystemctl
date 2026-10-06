from __future__ import annotations

import argparse
import dataclasses

import pytest

from pystemctl.bus import Scope
from pystemctl.cli.args import JournalArgs, RunArgs, ShowArgs, TailArgs
from pystemctl.cli.commands.run import strip_separator
from pystemctl.cli.parser import build_journal_parser, build_parser


@pytest.fixture(scope="module")
def parser() -> argparse.ArgumentParser:
    return build_parser()


def _parse(parser: argparse.ArgumentParser, argv: list[str]) -> argparse.Namespace:
    # Matches pystemctl.cli._run.
    return parser.parse_args(argv)


def test_every_bound_command_has_a_handler(parser: argparse.ArgumentParser) -> None:
    # The subparsers action holds the names, counting aliases only once.
    subparsers = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )
    for name, sub in subparsers.choices.items():
        assert callable(sub.get_default("handler")), name


def test_scope_defaults_to_user_and_json_off(parser: argparse.ArgumentParser) -> None:
    args = _parse(parser, ["list"])
    assert args.scope is Scope.USER
    assert args.json is False


def test_scope_is_shared_by_every_command(parser: argparse.ArgumentParser) -> None:
    # Every subcommand carries --user/--system/--json through the shared parent.
    # A target is supplied only where the command requires one.
    needed = {
        "status": "x.service",
        "cat": "x.service",
        "wait": "x.service",
        "tail": "x.service",
    }
    for command in ("list", "status", "jobs", "wait", "tail", "cat", "daemon-reload"):
        argv = [command]
        if command in needed:
            argv.append(needed[command])
        args = _parse(parser, [*argv, "--system", "--json"])
        assert args.scope is Scope.SYSTEM, command
        assert args.json is True, command


@pytest.mark.parametrize(
    "argv",
    [
        # run is absent: its positional is also named "command", so it cannot
        # share the argv[0] assertion. It has its own tests below.
        ["jobs", "--tag", "a", "--any-session", "--all"],
        ["list", "--all", "--type", "service", "--state", "running", "--ephemeral"],
        ["status", "x.service", "-n", "5", "--no-journal"],
        ["show", "x.service", "-P", "MainPID", "-P", "Result"],
        ["cat", "x.service"],
        ["is-active", "x.service"],
        ["enable", "x.service"],
    ],
)
def test_documented_flags_parse(parser: argparse.ArgumentParser, argv: list[str]) -> None:
    assert _parse(parser, argv).command == argv[0]


def test_run_tag_is_repeatable(parser: argparse.ArgumentParser) -> None:
    args = _parse(parser, ["run", "--tag", "a", "--tag", "b", "--", "true"])
    assert args.tags == ["a", "b"]


def test_run_dir_is_a_working_directory_alias(parser: argparse.ArgumentParser) -> None:
    args = _parse(parser, ["run", "--dir", "/srv/jobs", "--", "true"])
    assert args.working_directory == "/srv/jobs"


def test_tail_follows_until_exit_by_default(parser: argparse.ArgumentParser) -> None:
    # Bare tail streams to the end and reports the code; explicit -f keeps
    # the plain stream, which always exits 0.
    assert TailArgs.from_namespace(_parse(parser, ["tail", "x.service"])).until_exit is True
    assert (
        TailArgs.from_namespace(_parse(parser, ["tail", "--until-exit", "x.service"])).until_exit
        is True
    )
    explicit = TailArgs.from_namespace(_parse(parser, ["tail", "-f", "x.service"]))
    assert explicit.follow is True
    assert explicit.until_exit is False


def test_run_command_is_remainder(parser: argparse.ArgumentParser) -> None:
    # REMAINDER keeps the separating "--"; strip_separator removes it, so the
    # handler must never see it and this is the value it starts from.
    args = _parse(parser, ["run", "--", "sh", "-c", "echo hi"])
    assert strip_separator(args.command) == ["sh", "-c", "echo hi"]


def test_run_collect_is_tri_state(parser: argparse.ArgumentParser) -> None:
    assert _parse(parser, ["run", "--", "true"]).collect is None
    assert _parse(parser, ["run", "--collect", "--", "true"]).collect is True
    assert _parse(parser, ["run", "--no-collect", "--", "true"]).collect is False


def test_run_collect_flags_are_mutually_exclusive(parser: argparse.ArgumentParser) -> None:
    with pytest.raises(SystemExit):
        _parse(parser, ["run", "--collect", "--no-collect", "--", "true"])


def test_show_property_is_repeatable(parser: argparse.ArgumentParser) -> None:
    args = _parse(parser, ["show", "x.service", "-P", "MainPID", "-P", "Result"])
    assert args.properties == ["MainPID", "Result"]


def test_show_property_splits_commas(parser: argparse.ArgumentParser) -> None:
    # systemctl spells several properties -p A,B; accept that too. The split
    # lives in from_namespace, which is what dispatch hands the handler.
    ns = _parse(parser, ["show", "x.service", "-P", "ActiveState,Result"])
    assert ns.properties == ["ActiveState,Result"]
    assert ShowArgs.from_namespace(ns).properties == ["ActiveState", "Result"]


def test_target_selector_requires_one_of_unit_or_tag(parser: argparse.ArgumentParser) -> None:
    assert _parse(parser, ["wait", "x.service"]).unit == "x.service"
    assert _parse(parser, ["wait", "--tag", "a"]).tags == ["a"]
    with pytest.raises(SystemExit):
        _parse(parser, ["wait"])


def test_target_selector_tags_are_repeatable(parser: argparse.ArgumentParser) -> None:
    args = _parse(parser, ["tail", "-T", "a", "-T", "b"])
    assert args.tags == ["a", "b"]


def test_replay_default_is_per_command(parser: argparse.ArgumentParser) -> None:
    assert _parse(parser, ["logs", "x.service"]).lines is None
    assert _parse(parser, ["status", "x.service"]).lines == 10
    assert _parse(parser, ["tail", "x.service"]).lines == 200


def test_logs_takes_units_replay_and_follow(parser: argparse.ArgumentParser) -> None:
    args = _parse(parser, ["logs", "-f", "-n", "5", "a.service", "b.service"])
    assert args.units == ["a.service", "b.service"]
    assert args.follow is True
    assert args.lines == 5


def test_tail_takes_one_target_and_the_watch_flags(parser: argparse.ArgumentParser) -> None:
    args = _parse(parser, ["tail", "--grep", "boom", "--timeout", "2", "x.service"])
    assert args.unit == "x.service"
    assert args.grep == "boom"
    assert args.timeout == 2.0


def test_options_may_precede_or_follow_a_target(parser: argparse.ArgumentParser) -> None:
    # systemctl and journalctl accept either order, and so does this.
    before = _parse(parser, ["logs", "-f", "x.service"])
    after = _parse(parser, ["logs", "x.service", "-f"])
    assert before.units == after.units == ["x.service"]
    assert before.follow is after.follow is True


def test_tail_until_exit_is_its_own_flag(parser: argparse.ArgumentParser) -> None:
    assert _parse(parser, ["tail", "x.service", "--until-exit"]).until_exit is True


def test_journal_options_parse(parser: argparse.ArgumentParser) -> None:
    args = _parse(
        parser,
        ["logs", "x.service", "--since", "1h", "--until", "now", "-p", "err", "-o", "json"],
    )
    assert (args.since, args.until, args.priority, args.output) == ("1h", "now", "err", "json")


def test_boot_defaults_to_none_and_bare_flag_is_true(parser: argparse.ArgumentParser) -> None:
    assert _parse(parser, ["logs", "x.service"]).boot is None
    assert _parse(parser, ["logs", "x.service", "-b"]).boot is True


def test_list_aliases_resolve(parser: argparse.ArgumentParser) -> None:
    # argparse records the alias that was typed, not the canonical name, so the
    # handler is what proves the alias resolves.
    for alias in ("ls", "units"):
        args = _parse(parser, [alias])
        assert args.command == alias
        assert args.handler is _parse(parser, ["list"]).handler


def test_profile_action_defaults_to_list(parser: argparse.ArgumentParser) -> None:
    assert _parse(parser, ["profile"]).action == "list"
    assert _parse(parser, ["profile", "show", "ci"]).name == "ci"


def test_unknown_flag_is_rejected(parser: argparse.ArgumentParser) -> None:
    with pytest.raises(SystemExit):
        _parse(parser, ["list", "--definitely-not-a-flag"])


def test_help_groups_job_commands(parser: argparse.ArgumentParser) -> None:
    assert parser.epilog is not None
    assert "ephemeral jobs: run, jobs, wait, tail" in parser.epilog
    assert "unit control:" in parser.epilog


def _sub(parser: argparse.ArgumentParser, name: str) -> argparse.ArgumentParser:
    subparsers = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )
    return subparsers.choices[name]


@pytest.mark.parametrize(
    ("command", "pointer"),
    [("wait", "tail"), ("tail", "wait"), ("tail", "logs"), ("logs", "tail")],
)
def test_watch_commands_point_at_each_other(
    parser: argparse.ArgumentParser, command: str, pointer: str
) -> None:
    assert pointer in (_sub(parser, command).description or "")


def test_run_wait_help_mentions_streaming(parser: argparse.ArgumentParser) -> None:
    assert "streaming" in (_sub(parser, "run").description or "") or any(
        "streaming" in (action.help or "") for action in _sub(parser, "run")._actions
    )


def test_journal_parser_flags() -> None:
    parser = build_journal_parser()
    args = _parse(
        parser,
        ["-u", "a.service", "--user-unit", "b.service", "--json", "-n", "3", "-f", "-b"],
    )
    assert args.system_units == ["a.service"]
    assert args.user_units == ["b.service"]
    assert args.json is True
    assert args.lines == 3
    assert args.follow is True
    assert args.boot is True


_COMMAND_ARGV = {
    "run": ["run", "--", "true"],
    "list": ["list"],
    "ls": ["ls"],
    "units": ["units"],
    "list-unit-files": ["list-unit-files"],
    "status": ["status"],
    "start": ["start", "x.service"],
    "stop": ["stop", "x.service"],
    "restart": ["restart", "x.service"],
    "reload": ["reload", "x.service"],
    "rm": ["rm", "x.service"],
    "is-active": ["is-active", "x.service"],
    "is-failed": ["is-failed", "x.service"],
    "is-enabled": ["is-enabled", "x.service"],
    "enable": ["enable", "x.service"],
    "disable": ["disable", "x.service"],
    "cat": ["cat", "x.service"],
    "show": ["show"],
    "daemon-reload": ["daemon-reload"],
    "logs": ["logs"],
    "jobs": ["jobs"],
    "wait": ["wait", "x.service"],
    "tail": ["tail", "x.service"],
    "profile": ["profile"],
}


@pytest.mark.parametrize("command", sorted(_COMMAND_ARGV))
def test_every_command_converts_to_its_typed_args(
    parser: argparse.ArgumentParser, command: str
) -> None:
    """The parser and the typed args agree, in both directions.

    Every attribute a real parse sets has a field waiting for it, and the
    conversion runs without raising. A new flag without a field fails here,
    not silently at the handler.
    """
    args_type = _sub(parser, command).get_default("args_type")
    assert args_type is not None, command
    ns = _parse(parser, _COMMAND_ARGV[command])
    args_type.from_namespace(ns)
    parsed = set(vars(ns)) - {"handler", "args_type"}
    if not isinstance(ns.command, list):
        # Elsewhere "command" is the subcommand name argparse records, not a
        # flag; only run's positional shares the name and owns the field.
        parsed.discard("command")
    fields = {field.name for field in dataclasses.fields(args_type)}
    assert parsed == fields, command


def test_run_conversion_carries_every_flag(parser: argparse.ArgumentParser) -> None:
    ns = _parse(parser, ["run", "--tag", "a", "--wait", "--collect", "--", "true"])
    args = RunArgs.from_namespace(ns)
    assert args.tags == ["a"]
    assert args.wait is True
    assert args.collect is True
    assert args.command == ["--", "true"]
    assert args.scope is Scope.USER


def test_wait_conversion_defaults_match_the_parser(parser: argparse.ArgumentParser) -> None:
    ns = _parse(parser, ["wait", "--tag", "a"])
    args = _sub(parser, "wait").get_default("args_type").from_namespace(ns)
    assert args.unit is None
    assert args.tags == ["a"]
    assert args.lines == 200
    assert args.timeout is None
    assert args.grep is None


def test_journal_conversion_covers_the_journal_parser() -> None:
    ns = _parse(build_journal_parser(), ["-u", "a.service", "--json"])
    args = JournalArgs.from_namespace(ns)
    assert args.system_units == ["a.service"]
    assert args.user_units == []
    assert args.json is True
    assert args.output == "short"
    parsed = set(vars(ns))
    fields = {field.name for field in dataclasses.fields(JournalArgs)}
    assert parsed == fields
