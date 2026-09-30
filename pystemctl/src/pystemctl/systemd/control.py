"""Lifecycle operations and job waiting."""

from __future__ import annotations

import contextlib
import time
from typing import Any

import anyio
from jeepney import MatchRule
from jeepney.wrappers import DBusErrorResponse

from ..bus import JOB_INTERFACE, SYSTEMD_BUS_NAME, UNIT_INTERFACE, Bus
from .units import load_unit_path, unit_interface

_TERMINAL_JOB_STATES = frozenset({"done", "canceled", "failed", "timeout"})
_FINISHED_STATES = frozenset({"inactive", "failed"})


async def start_unit(bus: Bus, name: str, mode: str = "replace") -> str:
    return (await bus.manager("StartUnit", "ss", (name, mode)))[0]


async def stop_unit(bus: Bus, name: str, mode: str = "replace") -> str:
    return (await bus.manager("StopUnit", "ss", (name, mode)))[0]


async def restart_unit(bus: Bus, name: str, mode: str = "replace") -> str:
    return (await bus.manager("RestartUnit", "ss", (name, mode)))[0]


async def reload_unit(bus: Bus, name: str, mode: str = "replace") -> str:
    return (await bus.manager("ReloadUnit", "ss", (name, mode)))[0]


async def reset_failed_unit(bus: Bus, name: str) -> None:
    try:
        await bus.manager("ResetFailedUnit", "s", (name,))
    except DBusErrorResponse as error:
        if "NoSuchUnit" not in (error.name or ""):
            raise


async def reload_manager(bus: Bus) -> None:
    await bus.manager("Reload")


async def enable_unit(bus: Bus, name: str) -> list[tuple[str, str, str]]:
    changes = (await bus.manager("EnableUnitFiles", "asbb", ([name], False, False)))[1]
    return [tuple(change) for change in changes]


async def disable_unit(bus: Bus, name: str) -> list[tuple[str, str, str]]:
    changes = (await bus.manager("DisableUnitFiles", "asb", ([name], False)))[0]
    return [tuple(change) for change in changes]


async def wait_job(bus: Bus, job_path: str, timeout: float = 30.0) -> str:
    deadline = time.monotonic() + timeout
    while True:
        try:
            state = await bus.get_property(job_path, JOB_INTERFACE, "State")
        except DBusErrorResponse:
            return "done"
        if state in _TERMINAL_JOB_STATES:
            return state
        if time.monotonic() >= deadline:
            return "timeout"
        await anyio.sleep(0.1)


def _is_finished(props: dict[str, Any]) -> bool:
    if props.get("ActiveState") not in _FINISHED_STATES:
        return False
    job = props.get("Job")
    if isinstance(job, (tuple, list)) and job and job[0]:
        return False
    return True


async def wait_until_finished(bus: Bus, name: str, timeout: float | None = None) -> dict[str, Any]:
    """Wait until *name* is inactive or failed and has no job left.

    The unit may be collected the moment it stops, so the state is read while
    a ``PropertiesChanged`` signal still guarantees it exists; a one second
    poll is the fallback for a signal that does not arrive.
    """
    path = await load_unit_path(bus, name)
    rule = MatchRule(
        type="signal",
        sender=SYSTEMD_BUS_NAME,
        path=path,
        interface="org.freedesktop.DBus.Properties",
        member="PropertiesChanged",
    )
    await bus.add_match(rule)

    async def snapshot() -> dict[str, Any]:
        props = await bus.get_all(path, UNIT_INTERFACE)
        interface = unit_interface(name)
        if interface is not None:
            props.update(await bus.get_all(path, interface))
        return props

    async def wait() -> dict[str, Any]:
        with bus.filter(rule) as queue:
            while True:
                try:
                    props = await snapshot()
                except DBusErrorResponse:
                    return {}
                if _is_finished(props):
                    return props
                with anyio.move_on_after(1.0):
                    await queue.get()

    scoped = anyio.move_on_after(timeout) if timeout is not None else contextlib.nullcontext()
    result: dict[str, Any] | None = None
    with scoped:
        result = await wait()
    return result or {}
