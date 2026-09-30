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
from typing import Any

from jeepney import DBusAddress, new_method_call
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


@asynccontextmanager
async def connect(scope: Scope) -> AsyncIterator[Bus]:
    async with open_dbus_router(bus=bus_address(scope)) as router:
        yield Bus(router)
