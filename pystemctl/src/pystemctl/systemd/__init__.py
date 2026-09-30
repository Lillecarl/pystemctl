"""Typed operations on a systemd service manager.

Everything here either returns plain data or performs one manager operation.
There is no formatting and no argument parsing.
"""

from __future__ import annotations

from .control import (
    disable_unit,
    enable_unit,
    reload_manager,
    reload_unit,
    reset_failed_unit,
    restart_unit,
    start_unit,
    stop_unit,
    wait_job,
    wait_until_finished,
)
from .jobs import Job, collect_jobs
from .transient import (
    TransientSpec,
    build_transient_properties,
    generate_unit_name,
    replace_transient,
    resolve_executable,
    start_transient,
)
from .units import (
    Unit,
    get_unit_file_state,
    is_transient,
    list_unit_files,
    list_units,
    load_unit_path,
    normalize_unit_name,
    try_unit_properties,
    unit_active_state,
    unit_interface,
    unit_properties,
)

__all__ = [
    "Job",
    "TransientSpec",
    "Unit",
    "build_transient_properties",
    "collect_jobs",
    "disable_unit",
    "enable_unit",
    "generate_unit_name",
    "get_unit_file_state",
    "is_transient",
    "list_unit_files",
    "list_units",
    "load_unit_path",
    "normalize_unit_name",
    "reload_manager",
    "replace_transient",
    "reload_unit",
    "reset_failed_unit",
    "resolve_executable",
    "restart_unit",
    "start_transient",
    "start_unit",
    "stop_unit",
    "try_unit_properties",
    "unit_active_state",
    "unit_interface",
    "unit_properties",
    "wait_job",
    "wait_until_finished",
]
