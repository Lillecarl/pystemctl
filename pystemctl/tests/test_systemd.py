from __future__ import annotations

import contextlib
from functools import partial
from typing import Any

import anyio
import pytest
from jeepney.wrappers import DBusErrorResponse

from pystemctl import profiles
from pystemctl.bus import Bus, watch_properties
from pystemctl.cli.helpers import parse_property
from pystemctl.errors import PystemctlError
from pystemctl.systemd import (
    coerce_property_value,
    generate_unit_name,
    normalize_unit_name,
    unit_active_state,
    wait_job,
)


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


class _SignalMessage:
    def __init__(self, body: tuple[object, ...]) -> None:
        self.body = body


class _SignalQueue:
    """A signal queue fed from a script; hanging when empty like a live one."""

    def __init__(self, bodies: list[tuple[object, ...]]) -> None:
        self._bodies = bodies

    async def get(self) -> _SignalMessage:
        if self._bodies:
            return _SignalMessage(self._bodies.pop(0))
        await anyio.sleep(30)
        raise AssertionError("unreachable")


class _SignalBus(Bus):
    """A bus with a scripted job state and removal stream."""

    def __init__(self, states: list[str | None], bodies: list[tuple[object, ...]]) -> None:
        self._states = states
        self._bodies = bodies
        self.matches = 0

    async def get_property(self, path: str, interface: str, name: str) -> Any:
        state = self._states.pop(0)
        if state is None:
            raise _NoSuchUnit()
        return state

    async def add_match(self, rule: object) -> None:
        self.matches += 1

    @contextlib.contextmanager
    def filter(self, rule: object, *, queue: object = None) -> Any:
        yield _SignalQueue(self._bodies)


def _removed(
    job: str, result: str, unit: str = "x.service", job_id: int = 42
) -> tuple[object, ...]:
    return (job_id, job, unit, result)


def test_wait_job_gone_means_done() -> None:
    bus = _SignalBus([None], [])
    assert anyio.run(partial(wait_job, bus, "/job/1")) == "done"
    assert bus.matches == 0


def test_wait_job_returns_an_already_terminal_state() -> None:
    assert anyio.run(partial(wait_job, _SignalBus(["done"], []), "/job/1")) == "done"


def test_wait_job_resolves_on_the_removal_signal() -> None:
    """Another job's removal is ignored; ours ends the wait at once."""
    bus = _SignalBus(
        ["running", "running"],
        [_removed("/job/9", "done"), _removed("/job/1", "failed")],
    )
    assert anyio.run(partial(wait_job, bus, "/job/1", 5)) == "failed"
    assert bus.matches == 1


def test_wait_job_unknown_result_reads_as_failed() -> None:
    bus = _SignalBus(["running", "running"], [_removed("/job/1", "dependency")])
    assert anyio.run(partial(wait_job, bus, "/job/1", 5)) == "failed"


def test_wait_job_gives_up_at_the_timeout() -> None:
    bus = _SignalBus(["running", "running"], [])
    assert anyio.run(partial(wait_job, bus, "/job/1", 0.05)) == "timeout"


def test_properties_stream_decodes_changed_values() -> None:
    bus = _SignalBus(
        [],
        [("sig", {"Result": ("s", "success"), "ActiveState": ("s", "active")}, [])],
    )

    async def _main() -> dict[str, object]:
        async with watch_properties(bus, "/unit/path") as stream:
            return await stream.__anext__()

    assert anyio.run(_main) == {"Result": "success", "ActiveState": "active"}
    assert bus.matches == 1


@pytest.mark.parametrize(
    ("typename", "toml_value", "cli_text", "expected"),
    [
        ("b", True, "yes", True),
        ("b", False, "no", False),
        ("i", 5, "5", 5),
        ("as", ["a", "b"], "a,b", ["a", "b"]),
        ("s", "x", "x", "x"),
    ],
)
def test_property_spellings_agree(
    typename: str, toml_value: object, cli_text: str, expected: object
) -> None:
    """A TOML value and its --property string mean the same typed value."""
    assert profiles._typed_property("K", toml_value) == ("K", (typename, expected))
    assert parse_property(f"K:{typename}={cli_text}") == ("K", (typename, expected))


def test_property_coercion_rejects_garbage_loudly() -> None:
    with pytest.raises(PystemctlError, match="must be a number"):
        coerce_property_value("i", "abc")
    with pytest.raises(PystemctlError, match="unsupported property type"):
        parse_property("K:zzz=1")
