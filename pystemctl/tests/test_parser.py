from __future__ import annotations

import argparse

import pytest

from pystemctl.cli.parser import build_journal_parser, build_parser
from pystemctl.cli.commands.run import strip_separator
from pystemctl.bus import Scope


@pytest.fixture(scope="module")
def parser() -> argparse.ArgumentParser:
    return build_parser()


def _parse(parser: argparse.ArgumentParser, argv: list[str]) -> argparse.Namespace:
    # Matches pystemctl.cli._run.
    return parser.parse_args(argv)


def test_every_bound_command_has_a_handler(parser: argparse.ArgumentParser) -> None:
    # The subparsers action holds the names, counting aliases only once.
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    for name, sub in subparsers.choices.items():
        assert hasattr(sub.get_default("handler"), "__call__"), name


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
