"""Exceptions that carry a message meant for the user.

The command line layer prints one of these and returns the error's exit
code. Any other exception is a bug and is allowed to reach the traceback.
"""

from __future__ import annotations

from jeepney.wrappers import DBusErrorResponse


class PystemctlError(Exception):
    """A failure whose message is fit to show to the user."""

    exit_code = 1


class UnitNotFoundError(PystemctlError):
    """A unit name resolves to no loaded or loadable unit."""

    exit_code = 4

    def __init__(self, name: str) -> None:
        super().__init__(f"Unit {name} not found.")
        self.name = name


def is_no_such_unit(error: DBusErrorResponse) -> bool:
    """Whether a D-Bus error is systemd reporting no such unit."""
    return "NoSuchUnit" in (error.name or "")
