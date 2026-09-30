"""Unit objects and read-only queries against a service manager."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from jeepney.wrappers import DBusErrorResponse

from ..bus import UNIT_INTERFACE, Bus
from ..errors import UnitNotFound

UNIT_SUFFIXES = (
    ".service",
    ".socket",
    ".device",
    ".mount",
    ".automount",
    ".swap",
    ".target",
    ".path",
    ".timer",
    ".slice",
    ".scope",
)

_UNIT_INTERFACES = {
    ".service": "org.freedesktop.systemd1.Service",
    ".socket": "org.freedesktop.systemd1.Socket",
    ".mount": "org.freedesktop.systemd1.Mount",
    ".automount": "org.freedesktop.systemd1.Automount",
    ".swap": "org.freedesktop.systemd1.Swap",
    ".target": "org.freedesktop.systemd1.Target",
    ".path": "org.freedesktop.systemd1.Path",
    ".timer": "org.freedesktop.systemd1.Timer",
    ".slice": "org.freedesktop.systemd1.Slice",
    ".scope": "org.freedesktop.systemd1.Scope",
}


@dataclass(slots=True)
class Unit:
    """One row of ``ListUnits``."""

    name: str
    description: str
    load_state: str
    active_state: str
    sub_state: str
    following: str
    path: str
    job_id: int
    job_type: str
    job_path: str

    @classmethod
    def from_row(cls, row: Sequence[Any]) -> Unit:
        return cls(*row)

    @property
    def is_active(self) -> bool:
        return self.active_state == "active"


def normalize_unit_name(name: str) -> str:
    if any(name.endswith(suffix) for suffix in UNIT_SUFFIXES):
        return name
    return f"{name}.service"


def unit_interface(name: str) -> str | None:
    for suffix, interface in _UNIT_INTERFACES.items():
        if name.endswith(suffix):
            return interface
    return None


async def list_units(bus: Bus) -> list[Unit]:
    rows = (await bus.manager("ListUnits"))[0]
    return [Unit.from_row(row) for row in rows]


async def list_unit_files(bus: Bus) -> list[tuple[str, str]]:
    rows = (await bus.manager("ListUnitFiles"))[0]
    return [(path, state) for path, state in rows]


async def load_unit_path(bus: Bus, name: str) -> str:
    try:
        return (await bus.manager("GetUnit", "s", (name,)))[0]
    except DBusErrorResponse as error:
        if "NoSuchUnit" not in (error.name or ""):
            raise
    try:
        return (await bus.manager("LoadUnit", "s", (name,)))[0]
    except DBusErrorResponse as error:
        raise UnitNotFound(name) from error


async def unit_properties(bus: Bus, name: str) -> dict[str, Any]:
    path = await load_unit_path(bus, name)
    props = await bus.get_all(path, UNIT_INTERFACE)
    interface = unit_interface(name)
    if interface is not None:
        props.update(await bus.get_all(path, interface))
    return props


async def try_unit_properties(bus: Bus, name: str) -> dict[str, Any]:
    try:
        return await unit_properties(bus, name)
    except UnitNotFound:
        return {}


async def unit_active_state(bus: Bus, name: str) -> str:
    try:
        path = (await bus.manager("GetUnit", "s", (name,)))[0]
    except DBusErrorResponse as error:
        if "NoSuchUnit" in (error.name or ""):
            return "inactive"
        raise
    return await bus.get_property(path, UNIT_INTERFACE, "ActiveState")


async def get_unit_file_state(bus: Bus, name: str) -> str:
    return (await bus.manager("GetUnitFileState", "s", (name,)))[0]


async def is_transient(bus: Bus, unit: Unit) -> bool:
    props = await bus.get_all(unit.path, UNIT_INTERFACE)
    return bool(props.get("Transient", False))


def environment_of(props: dict[str, Any]) -> dict[str, str]:
    """Parse the unit properties' ``Environment`` into a mapping.

    systemd serialises the environment as a list of ``KEY=VALUE`` pairs, with
    a value omitted for an inherited variable.
    """
    raw = props.get("Environment")
    if not isinstance(raw, (list, tuple)):
        return {}
    environment: dict[str, str] = {}
    for item in raw:
        key, separator, value = str(item).partition("=")
        environment[key] = value if separator else ""
    return environment
