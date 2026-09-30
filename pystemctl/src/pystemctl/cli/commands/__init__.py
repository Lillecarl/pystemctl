"""Command handlers, one module per concern."""

from __future__ import annotations

from .control import cmd_reload, cmd_restart, cmd_rm, cmd_start, cmd_stop
from .jobs import cmd_jobs
from .logs import cmd_logs
from .profile import cmd_profile
from .query import (
    cmd_cat,
    cmd_daemon_reload,
    cmd_disable,
    cmd_enable,
    cmd_is_active,
    cmd_is_enabled,
    cmd_is_failed,
    cmd_show,
)
from .run import cmd_run
from .tail import cmd_tail
from .units import cmd_list, cmd_list_unit_files, cmd_status
from .wait import cmd_wait

__all__ = [
    "cmd_cat",
    "cmd_daemon_reload",
    "cmd_disable",
    "cmd_enable",
    "cmd_is_active",
    "cmd_is_enabled",
    "cmd_is_failed",
    "cmd_jobs",
    "cmd_list",
    "cmd_list_unit_files",
    "cmd_logs",
    "cmd_profile",
    "cmd_reload",
    "cmd_restart",
    "cmd_rm",
    "cmd_run",
    "cmd_show",
    "cmd_start",
    "cmd_status",
    "cmd_stop",
    "cmd_tail",
]
