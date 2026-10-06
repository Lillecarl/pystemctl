"""The man pages stay complete: every subcommand and flag is documented."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from pystemctl.cli.parser import build_journal_parser, build_parser

MAN_DIR = Path(__file__).parent.parent / "man"

_LONG_FLAG = re.compile(r"\*--([a-z][a-z-]*)")


def _pages() -> dict[str, str]:
    return {path.stem.split(".")[0]: path.read_text() for path in sorted(MAN_DIR.glob("*.scd"))}


def _subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    action = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )
    return action.choices


def _long_flags(parser: argparse.ArgumentParser) -> set[str]:
    found = set()
    for action in parser._actions:
        found.update(option for option in action.option_strings if option.startswith("--"))
        if isinstance(action, argparse._SubParsersAction):
            for sub in action.choices.values():
                found |= _long_flags(sub)
    return found


def test_man_pages_exist_for_both_entry_points() -> None:
    assert (MAN_DIR / "pystemctl.1.scd").is_file()
    assert (MAN_DIR / "pyjournalctl.1.scd").is_file()


def test_every_subcommand_is_documented() -> None:
    text = _pages()["pystemctl"]
    for name in _subparsers(build_parser()):
        assert re.search(rf"\*{re.escape(name)}\*", text), name


def test_every_documented_flag_still_exists() -> None:
    pages = _pages()
    known = _long_flags(build_parser()) | _long_flags(build_journal_parser())
    known |= {"--help"}
    for page, text in pages.items():
        for flag in set(_LONG_FLAG.findall(text)):
            assert f"--{flag}" in known, f"{page}: --{flag}"


def test_every_output_mode_is_documented() -> None:
    from pystemctl.journal import OUTPUT_MODES

    text = _pages()["pyjournalctl"]
    for mode in OUTPUT_MODES:
        assert mode in text, mode
