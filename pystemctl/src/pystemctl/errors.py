"""Exceptions that carry a message meant for the user.

The command line layer prints one of these and returns a non-zero status.
Any other exception is a bug and is allowed to reach the traceback.
"""

from __future__ import annotations


class PystemctlError(Exception):
    """A failure whose message is fit to show to the user."""


class UnitNotFoundError(PystemctlError):
    """A unit name resolves to no loaded or loadable unit."""

    def __init__(self, name: str) -> None:
        super().__init__(f"Unit {name} not found.")
        self.name = name
