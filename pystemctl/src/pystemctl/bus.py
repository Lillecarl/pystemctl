"""Connection to a systemd manager over D-Bus.

Talks to the service manager through jeepney's asyncio transport. The
concurrency framework is anyio on its asyncio backend, so jeepney's asyncio
primitives share the running loop.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from enum import StrEnum
from typing import Any, NamedTuple

from jeepney import DBusAddress, MatchRule, new_method_call
from jeepney.bus_messages import message_bus
from jeepney.io.asyncio import DBusRouter, open_dbus_router
from jeepney.wrappers import unwrap_msg

SYSTEMD_BUS_NAME = "org.freedesktop.systemd1"
SYSTEMD_PATH = "/org/freedesktop/systemd1"

MANAGER_INTERFACE = "org.freedesktop.systemd1.Manager"
UNIT_INTERFACE = "org.freedesktop.systemd1.Unit"
JOB_INTERFACE = "org.freedesktop.systemd1.Job"
PROPERTIES_INTERFACE = "org.freedesktop.DBus.Properties"


class Scope(StrEnum):
    """Which service manager to talk to."""

    USER = "user"
    SYSTEM = "system"


def bus_address(scope: Scope) -> str:
    """Return a D-Bus transport address for *scope*.

    The user manager's private socket rejects the Hello that jeepney sends,
    so the session bus is used, which every user manager answers.
    """
    if scope is Scope.SYSTEM:
        return os.environ.get("DBUS_SYSTEM_BUS_ADDRESS") or (
            "unix:path=/run/dbus/system_bus_socket"
        )
    address = os.environ.get("DBUS_SESSION_BUS_ADDRESS")
    if address:
        return address
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime:
        raise RuntimeError(
            "no session bus address: set DBUS_SESSION_BUS_ADDRESS or XDG_RUNTIME_DIR"
        )
    return f"unix:path={runtime}/bus"


class Bus:
    """Thin typed wrapper over a jeepney router."""

    def __init__(self, router: DBusRouter) -> None:
        self._router = router

    async def call(
        self,
        path: str,
        interface: str,
        method: str,
        signature: str | None = None,
        body: tuple[Any, ...] = (),
    ) -> tuple[Any, ...]:
        address = DBusAddress(path, bus_name=SYSTEMD_BUS_NAME).with_interface(interface)
        message = new_method_call(address, method, signature, body)
        return unwrap_msg(await self._router.send_and_get_reply(message))

    async def manager(
        self,
        method: str,
        signature: str | None = None,
        body: tuple[Any, ...] = (),
    ) -> tuple[Any, ...]:
        return await self.call(SYSTEMD_PATH, MANAGER_INTERFACE, method, signature, body)

    async def get_property(self, path: str, interface: str, name: str) -> Any:
        variant = (await self.call(path, PROPERTIES_INTERFACE, "Get", "ss", (interface, name)))[0]
        return variant[1]

    async def get_all(self, path: str, interface: str) -> dict[str, Any]:
        raw = (await self.call(path, PROPERTIES_INTERFACE, "GetAll", "s", (interface,)))[0]
        return {key: value for key, (_signature, value) in raw.items()}

    async def add_match(self, rule: Any) -> None:
        await self._router.send_and_get_reply(message_bus.AddMatch(rule))

    def filter(self, rule: Any, *, queue: Any = None) -> Any:
        return self._router.filter(rule, queue=queue)


class PropertiesStream:
    """An async iterator of PropertiesChanged payloads for one unit path.

    A class rather than a generator on purpose: timing out a ``queue.get``
    closes a generator, silently turning the stream into a poll loop, while
    a fresh ``__anext__`` here simply awaits again.
    """

    def __init__(self, queue: Any) -> None:
        self._queue = queue

    def __aiter__(self) -> PropertiesStream:
        return self

    async def __anext__(self) -> dict[str, Any]:
        message = await self._queue.get()
        _signature, changed, _invalidated = message.body
        return {key: value[1] for key, value in changed.items()}


class JobRemoval(NamedTuple):
    """A JobRemoved signal: the finished job's id, path, unit, and result."""

    id: int
    job: str
    unit: str
    result: str


class RemovalStream:
    """An async iterator of the manager's JobRemoved signals."""

    def __init__(self, queue: Any) -> None:
        self._queue = queue

    def __aiter__(self) -> RemovalStream:
        return self

    async def __anext__(self) -> JobRemoval:
        message = await self._queue.get()
        return JobRemoval(*message.body)


@asynccontextmanager
async def watch_properties(bus: Bus, path: str) -> AsyncIterator[PropertiesStream]:
    """Stream the PropertiesChanged signals for the unit at *path*."""
    rule = MatchRule(
        type="signal",
        sender=SYSTEMD_BUS_NAME,
        path=path,
        interface=PROPERTIES_INTERFACE,
        member="PropertiesChanged",
    )
    await bus.add_match(rule)
    with bus.filter(rule) as queue:
        yield PropertiesStream(queue)


@asynccontextmanager
async def watch_removals(bus: Bus) -> AsyncIterator[RemovalStream]:
    """Stream the manager's JobRemoved signals."""
    rule = MatchRule(
        type="signal",
        sender=SYSTEMD_BUS_NAME,
        path=SYSTEMD_PATH,
        interface=MANAGER_INTERFACE,
        member="JobRemoved",
    )
    await bus.add_match(rule)
    with bus.filter(rule) as queue:
        yield RemovalStream(queue)


@asynccontextmanager
async def connect(scope: Scope) -> AsyncIterator[Bus]:
    async with open_dbus_router(bus=bus_address(scope)) as router:
        yield Bus(router)
