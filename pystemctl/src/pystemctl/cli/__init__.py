"""Command line entry points."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Awaitable, Callable, Sequence

import anyio
from jeepney.wrappers import DBusErrorResponse

from ..errors import PystemctlError
from .dispatch import dispatch, journal_dispatch
from .parser import build_journal_parser, build_parser, register_completers

PYTHON_ARGCOMPLETE_OK = True


def _autocomplete(parser: argparse.ArgumentParser) -> None:
    try:
        import argcomplete
    except ImportError:
        return
    register_completers(parser)
    argcomplete.autocomplete(parser)


def _run(
    prefix: str,
    build_parser: Callable[[], argparse.ArgumentParser],
    dispatch: Callable[[argparse.Namespace], Awaitable[int]],
    argv: Sequence[str] | None,
) -> int:
    parser = build_parser()
    _autocomplete(parser)
    args = parser.parse_args(argv)
    try:
        return anyio.run(dispatch, args, backend="asyncio")
    except KeyboardInterrupt:
        return 130
    except PystemctlError as error:
        print(f"{prefix}: {error}", file=sys.stderr)
        return error.exit_code
    except (DBusErrorResponse, RuntimeError, FileNotFoundError) as error:
        print(f"{prefix}: {error}", file=sys.stderr)
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    return _run("pystemctl", build_parser, dispatch, argv)


def journalctl_main(argv: Sequence[str] | None = None) -> int:
    return _run("pyjournalctl", build_journal_parser, journal_dispatch, argv)
