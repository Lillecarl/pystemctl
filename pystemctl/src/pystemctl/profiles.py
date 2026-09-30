"""Command profiles: named defaults for an ephemeral job.

A profile is a TOML file under the platformdirs config path, one file with a
``[profiles.<name>]`` table each. It names the environment variables to copy
from the caller and how to choose the working directory, so a systemd unit --
which does not inherit the caller's environment -- still gets the context a
script runner would.
"""

from __future__ import annotations

import fnmatch
import os
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

from platformdirs import site_config_dir, user_config_dir

from .errors import PystemctlError

APP_NAME = "pystemctl"

WorkingDirectoryMode = Literal["caller", "static", "as-is"]


@dataclass(slots=True)
class Profile:
    """The settings a profile contributes to a run.

    ``inherit_env`` entries are variable names or glob patterns resolved
    against the caller's environment when the job starts, so a value never
    has to be written to disk. ``env`` holds fixed values for the rest.
    """

    name: str
    description: str | None = None
    inherit_env: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)
    working_directory: str | None = None
    working_directory_mode: WorkingDirectoryMode = "caller"
    unit_type: str | None = None
    tags: tuple[str, ...] = ()
    slice_name: str | None = None
    nice: int | None = None
    runtime_max_sec: float | None = None
    remain_after_exit: bool = False
    no_collect: bool = False
    properties: Mapping[str, tuple[str, Any]] = field(default_factory=dict)


def config_dirs() -> list[Path]:
    """Profile search path: the user's config first, then the system's."""
    return [
        Path(user_config_dir(APP_NAME)),
        Path(site_config_dir(APP_NAME)),
    ]


def config_files() -> list[Path]:
    return [directory / "profiles.toml" for directory in config_dirs()]


def load_profiles() -> dict[str, Profile]:
    """Read every profile from the search path.

    A later file overrides a profile of the same name, so a user profile
    shadows a system one. A missing file is not an error.
    """
    profiles: dict[str, Profile] = {}
    for path in config_files():
        if not path.is_file():
            continue
        try:
            data = tomllib.loads(path.read_text())
        except (OSError, tomllib.TOMLDecodeError) as error:
            raise PystemctlError(f"{path}: {error}") from error
        for name, table in data.get("profiles", {}).items():
            profiles[name] = _profile_from_table(name, table, path)
    return profiles


def _profile_from_table(name: str, table: Mapping[str, Any], path: Path) -> Profile:
    known = {
        "description",
        "inherit_env",
        "env",
        "working_directory",
        "working_directory_mode",
        "unit_type",
        "tags",
        "slice",
        "nice",
        "runtime_max",
        "remain_after_exit",
        "no_collect",
        "properties",
    }
    unknown = set(table) - known
    if unknown:
        raise PystemctlError(f"{path}: profile {name!r}: unknown keys: {', '.join(sorted(unknown))}")

    mode = table.get("working_directory_mode", "caller")
    if mode not in ("caller", "static", "as-is"):
        raise PystemctlError(f"{path}: profile {name!r}: bad working_directory_mode {mode!r}")

    properties: dict[str, tuple[str, Any]] = {}
    for key, value in table.get("properties", {}).items():
        properties[key] = _typed_property(key, value)

    return Profile(
        name=name,
        description=table.get("description"),
        inherit_env=tuple(table.get("inherit_env", ())),
        env=dict(table.get("env", {})),
        working_directory=table.get("working_directory"),
        working_directory_mode=mode,
        unit_type=table.get("unit_type"),
        tags=tuple(table.get("tags", ())),
        slice_name=table.get("slice"),
        nice=table.get("nice"),
        runtime_max_sec=table.get("runtime_max"),
        remain_after_exit=bool(table.get("remain_after_exit", False)),
        no_collect=bool(table.get("no_collect", False)),
        properties=properties,
    )


def _typed_property(name: str, value: Any) -> tuple[str, Any]:
    if isinstance(value, bool):
        return name, ("b", value)
    if isinstance(value, int):
        return name, ("i", value)
    if isinstance(value, list):
        return name, ("as", [str(item) for item in value])
    return name, ("s", str(value))


def resolve_environment(
    profile: Profile,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Expand a profile's environment for one run.

    Patterns in ``inherit_env`` are matched against the caller's environment.
    Fixed ``env`` values win over inherited ones of the same name.
    """
    source = os.environ if environ is None else environ
    resolved: dict[str, str] = {}
    for pattern in profile.inherit_env:
        for key in _matching_keys(pattern, source):
            resolved[key] = source[key]
    resolved.update(profile.env)
    return resolved


def _matching_keys(pattern: str, source: Mapping[str, str]) -> Iterable[str]:
    if any(char in pattern for char in "*?["):
        return [key for key in source if fnmatch.fnmatchcase(key, pattern)]
    return [pattern] if pattern in source else []


def resolve_working_directory(profile: Profile, *, cwd: str | None = None) -> str | None:
    """Choose the working directory for one run.

    ``caller`` follows the invoking process, ``static`` uses the profile's
    fixed path, and ``as-is`` passes the configured path through untouched.
    """
    if profile.working_directory_mode == "caller":
        return cwd if cwd is not None else os.getcwd()
    return profile.working_directory


def apply_cli_overrides(profile: Profile, args: Any) -> Profile:
    """Return *profile* with any explicitly set command-line value winning."""
    changes: dict[str, Any] = {}
    if getattr(args, "type", None):
        changes["unit_type"] = args.type
    if getattr(args, "description", None):
        changes["description"] = args.description
    if getattr(args, "working_directory", None):
        changes["working_directory"] = args.working_directory
        changes["working_directory_mode"] = "as-is"
    if getattr(args, "tags", None):
        changes["tags"] = tuple(dict.fromkeys((*profile.tags, *args.tags)))
    if getattr(args, "slice_name", None):
        changes["slice_name"] = args.slice_name
    if getattr(args, "nice", None) is not None:
        changes["nice"] = args.nice
    if getattr(args, "runtime_max", None) is not None:
        changes["runtime_max_sec"] = args.runtime_max
    return replace(profile, **changes) if changes else profile
