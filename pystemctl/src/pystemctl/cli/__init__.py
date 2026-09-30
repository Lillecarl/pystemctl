"""Command line entry points."""

from __future__ import annotations

import sys
from collections.abc import Sequence

import anyio
from jeepney.wrappers import DBusErrorResponse

from ..errors import PystemctlError
from .dispatch import dispatch, journal_dispatch
from .parser import build_journal_parser, build_parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return anyio.run(dispatch, args, backend="asyncio")
    except KeyboardInterrupt:
        return 130
    except (PystemctlError, DBusErrorResponse, RuntimeError, FileNotFoundError) as error:
        print(f"pystemctl: {error}", file=sys.stderr)
        return 1


def journalctl_main(argv: Sequence[str] | None = None) -> int:
    args = build_journal_parser().parse_args(argv)
    try:
        return anyio.run(journal_dispatch, args, backend="asyncio")
    except KeyboardInterrupt:
        return 130
    except PystemctlError as error:
        print(f"pyjournalctl: {error}", file=sys.stderr)
        return 1
