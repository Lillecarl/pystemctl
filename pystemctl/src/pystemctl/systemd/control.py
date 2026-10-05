"""Lifecycle operations and job waiting."""

from __future__ import annotations

import contextlib
import time
from typing import Any

import anyio
from jeepney import MatchRule
from jeepney.wrappers import DBusErrorResponse

from ..bus import JOB_INTERFACE, SYSTEMD_BUS_NAME, UNIT_INTERFACE, Bus
from ..errors import is_no_such_unit
from .units import load_unit_path, unit_interface

_TERMINAL_JOB_STATES = frozenset({"done", "canceled", "failed", "timeout"})
_FINISHED_STATES = frozenset({"inactive", "failed"})

# The service properties the exit status is reconstructed from, taken from the
# PropertiesChanged payload because they reset once the unit stops.
_INTERESTING = ("Result", "ExecMainStatus", "ExecMainCode", "ActiveState", "SubState")


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
        if not is_no_such_unit(error):
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


def unit_finished(props: dict[str, Any]) -> bool:
    state = props.get("ActiveState")
    # A oneshot with RemainAfterExit=yes parks in active/exited once its
    # process is gone: nothing will ever run again, so it counts as finished
    # even though systemd still calls it active.
    parked = state == "active" and props.get("SubState") == "exited"
    if state not in _FINISHED_STATES and not parked:
        return False
    job = props.get("Job")
    if isinstance(job, (tuple, list)) and job and job[0]:
        return False
    # A service reports ActiveState=inactive on one PropertiesChanged emission
    # and Result on a later one, so stopping at the state alone reads a stale
    # "success". Waiting for Result is what makes --wait return the real code.
    if props.get("Type") is not None and props.get("Result") is None:
        return False
    return True


async def wait_until_finished(bus: Bus, name: str, timeout: float | None = None) -> dict[str, Any]:
    """Wait until *name* has stopped and has no job left.

    A oneshot parked by RemainAfterExit counts as stopped: its process is
    gone and only the remembered result remains.

    The unit may be collected the moment it stops, so the state is read while
    a ``PropertiesChanged`` signal still guarantees it exists; a one second
    poll is the fallback for a signal that does not arrive.
    """
    path = await load_unit_path(bus, name)
    properties_rule = MatchRule(
        type="signal",
        sender=SYSTEMD_BUS_NAME,
        path=path,
        interface="org.freedesktop.DBus.Properties",
        member="PropertiesChanged",
    )
    await bus.add_match(properties_rule)

    async def snapshot() -> dict[str, Any]:
        props = await bus.get_all(path, UNIT_INTERFACE)
        interface = unit_interface(name)
        if interface is not None:
            props.update(await bus.get_all(path, interface))
        return props

    outcome: dict[str, Any] = {}

    async def watch_state(properties: Any, group: anyio.abc.TaskGroup) -> None:
        while True:
            received: Any = None
            with anyio.move_on_after(1.0):
                received = await properties.get()
            if received is not None:
                # The signal body carries the values as they were at the moment
                # of the change. Reading them here avoids racing the reset that
                # follows the stop, which a fresh GetAll would lose.
                _signature, changed, _invalidated = received.body
                for key in _INTERESTING:
                    if key in changed:
                        outcome.setdefault("changes", {})[key] = changed[key][1]
            try:
                props = await snapshot()
            except DBusErrorResponse:
                group.cancel_scope.cancel()
                return
            if props.get("Type") is not None and unit_finished(props):
                outcome["props"] = props
                group.cancel_scope.cancel()
                return

    async def wait() -> dict[str, Any]:
        outcome.clear()
        with bus.filter(properties_rule) as properties:
            async with anyio.create_task_group() as group:
                group.start_soon(watch_state, properties, group)
        props = outcome.get("props") or {}
        changes = outcome.get("changes") or {}
        return {**props, **changes}

    scoped = anyio.move_on_after(timeout) if timeout is not None else contextlib.nullcontext()
    result: dict[str, Any] | None = None
    with scoped:
        result = await wait()
    return result or {}
