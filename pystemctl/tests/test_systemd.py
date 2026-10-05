from __future__ import annotations

from typing import Any

import anyio
from jeepney.wrappers import DBusErrorResponse

from pystemctl.bus import Bus
from pystemctl.systemd import generate_unit_name, normalize_unit_name, unit_active_state


def test_normalize_appends_service() -> None:
    assert normalize_unit_name("foo") == "foo.service"
    assert normalize_unit_name("foo.service") == "foo.service"


def test_normalize_keeps_known_suffix() -> None:
    assert normalize_unit_name("foo.timer") == "foo.timer"
    assert normalize_unit_name("foo.socket") == "foo.socket"


def test_generate_unit_name() -> None:
    name = generate_unit_name(["sleep", "5"])
    assert name.startswith("pystemctl-sleep-")
    assert name.endswith(".service")


def test_generate_unit_name_sanitizes() -> None:
    name = generate_unit_name(["/usr/bin/some daft/name"])
    assert name.startswith("pystemctl-name-")


def test_generate_unit_name_is_unique() -> None:
    assert generate_unit_name(["sleep"]) != generate_unit_name(["sleep"])


class _NoSuchUnit(DBusErrorResponse):
    def __init__(self) -> None:
        self.name = "org.freedesktop.systemd1.NoSuchUnit"
        self.data = ()


class _MissingBus(Bus):
    """A manager that has never heard of any unit."""

    def __init__(self) -> None:
        pass

    async def manager(self, *args: Any, **kwargs: Any) -> Any:
        raise _NoSuchUnit()


def test_unit_active_state_reports_unknown_when_missing() -> None:
    assert anyio.run(unit_active_state, _MissingBus(), "nope.service") == "unknown"
