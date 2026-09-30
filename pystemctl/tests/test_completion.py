from __future__ import annotations

from pystemctl import cli
from pystemctl.cli.parser import build_journal_parser, build_parser


def test_argcomplete_marker_present() -> None:
    # argcomplete looks for this string in the first 1 KiB of the module the
    # console script imports, so it must stay near the top of pystemctl.cli.
    source = cli.__file__
    assert source is not None
    with open(source) as handle:
        assert "PYTHON_ARGCOMPLETE_OK" in handle.read(1024)


def test_parsers_build_for_completion() -> None:
    assert build_parser().prog == "pystemctl"
    assert build_journal_parser().prog == "pyjournalctl"
