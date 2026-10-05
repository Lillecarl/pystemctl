"""Creating transient (ephemeral) units.

A transient unit exists only in the running manager. With ``CollectMode`` set
it is unloaded again as soon as it stops, which is what makes it ephemeral.
"""

from __future__ import annotations

import os
import secrets
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from jeepney.wrappers import DBusErrorResponse

from ..bus import Bus
from ..errors import PystemctlError
from .tags import SESSION_ENV, TAG_FIELD, TAGS_ENV, tags_to_environment


@dataclass(slots=True)
class TransientSpec:
    """A transient service to hand to ``StartTransientUnit``."""

    name: str
    argv: Sequence[str]
    description: str | None = None
    unit_type: str = "simple"
    working_directory: str | None = None
    environment: Mapping[str, str] = field(default_factory=dict)
    properties: Mapping[str, tuple[str, Any]] = field(default_factory=dict)
    remain_after_exit: bool = False
    collect: bool = True
    standard_output: str = "journal"
    standard_error: str = "journal"
    runtime_max_sec: float | None = None
    nice: int | None = None
    slice_name: str | None = None
    tags: Sequence[str] = ()
    session: str | None = None
    # Hold the unit until this connection drops. A collecting unit is otherwise
    # unloaded the instant it stops, before its Result can be read, so a waiter
    # that needs the exit status has to pin it.
    pin: bool = False

    def unit_environment(self) -> dict[str, str]:
        """The full environment, with the reserved tag variables merged in.

        A tag value given in ``environment`` directly is kept, so a caller can
        set the session without going through the ``session`` field.
        """
        merged = dict(self.environment)
        if self.tags and TAGS_ENV not in merged:
            merged[TAGS_ENV] = tags_to_environment(self.tags)
        if self.session and SESSION_ENV not in merged:
            merged[SESSION_ENV] = self.session
        return merged


def generate_unit_name(command: Sequence[str]) -> str:
    program = os.path.basename(command[0]) if command else "job"
    slug = "".join(ch if ch.isalnum() else "-" for ch in program).strip("-").lower()
    slug = (slug or "job")[:40]
    return f"pystemctl-{slug}-{secrets.token_hex(3)}.service"


def resolve_executable(command: str) -> str:
    if os.path.sep in command:
        path = os.path.abspath(command)
        if not os.path.exists(path):
            raise PystemctlError(f"executable not found: {command}")
        return path
    found = shutil.which(command)
    if found is None:
        raise PystemctlError(f"executable not found in PATH: {command}")
    return found


def build_transient_properties(spec: TransientSpec) -> list[tuple[str, tuple[str, Any]]]:
    properties: list[tuple[str, tuple[str, Any]]] = [
        ("Description", ("s", spec.description or spec.name)),
        ("ExecStart", ("a(sasb)", [(resolve_executable(spec.argv[0]), list(spec.argv), False)])),
        ("Type", ("s", spec.unit_type)),
        ("StandardOutput", ("s", spec.standard_output)),
        ("StandardError", ("s", spec.standard_error)),
    ]
    if spec.collect:
        properties.append(("CollectMode", ("s", "inactive-or-failed")))
    if spec.remain_after_exit:
        properties.append(("RemainAfterExit", ("b", True)))
    if spec.working_directory:
        properties.append(("WorkingDirectory", ("s", spec.working_directory)))
    environment = spec.unit_environment()
    if environment:
        properties.append(
            ("Environment", ("as", [f"{key}={value}" for key, value in environment.items()]))
        )
    if spec.runtime_max_sec is not None:
        properties.append(("RuntimeMaxUSec", ("t", int(spec.runtime_max_sec * 1_000_000))))
    if spec.nice is not None:
        properties.append(("Nice", ("i", spec.nice)))
    if spec.slice_name:
        properties.append(("Slice", ("s", spec.slice_name)))
    if spec.pin:
        properties.append(("AddRef", ("b", True)))
    journal_tags = [
        f"{TAG_FIELD}={tag}".encode()
        for tag in spec.tags
        if tag and "\n" not in tag and "\x00" not in tag
    ]
    if journal_tags:
        properties.append(("LogExtraFields", ("aay", journal_tags)))
    properties.extend(spec.properties.items())
    return properties


async def start_transient(bus: Bus, spec: TransientSpec, mode: str = "fail") -> str:
    body = (spec.name, mode, build_transient_properties(spec), [])
    return (await bus.manager("StartTransientUnit", "ssa(sv)a(sa(sv))", body))[0]


async def replace_transient(bus: Bus, spec: TransientSpec) -> str:
    """Start *spec*, removing any loaded unit of the same name first.

    ``StartTransientUnit`` refuses a name that is already loaded, whatever the
    job mode: a job mode only replaces a queued job. Stopping the old unit and
    clearing a failure record returns the name to a pristine state.
    """
    from .control import reset_failed_unit, stop_unit, wait_job

    try:
        job = await stop_unit(bus, spec.name)
    except DBusErrorResponse as error:
        if "NoSuchUnit" not in (error.name or ""):
            raise
    else:
        await wait_job(bus, job)
    await reset_failed_unit(bus, spec.name)
    return await start_transient(bus, spec, mode="fail")
