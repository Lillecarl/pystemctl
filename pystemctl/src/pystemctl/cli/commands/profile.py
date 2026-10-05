"""Inspect command profiles."""

from __future__ import annotations

import argparse
import json

from ... import profiles
from ...bus import Bus
from ...errors import PystemctlError
from ...render import format_table


async def cmd_profile(_bus: Bus, args: argparse.Namespace) -> int:
    available = profiles.load_profiles()

    if args.action == "path":
        for path in profiles.config_files():
            print(path)
        return 0

    if args.action == "list":
        if args.json:
            print(json.dumps(sorted(available)))
            return 0
        if not available:
            print("No profiles defined.")
            print("Search path:", ", ".join(str(path) for path in profiles.config_files()))
            return 0
        rows = [[name, profile.description or ""] for name, profile in sorted(available.items())]
        print(format_table(["PROFILE", "DESCRIPTION"], rows))
        return 0

    if not args.name:
        raise PystemctlError("profile show needs a NAME")
    if args.name not in available:
        raise PystemctlError(f"profile {args.name!r} not found")

    profile = available[args.name]
    if args.json:
        print(
            json.dumps(
                {
                    "name": profile.name,
                    "description": profile.description,
                    "inherit_env": list(profile.inherit_env),
                    "env": dict(profile.env),
                    "working_directory": profile.working_directory,
                    "working_directory_mode": profile.working_directory_mode,
                    "unit_type": profile.unit_type,
                    "tags": list(profile.tags),
                    "slice": profile.slice_name,
                    "nice": profile.nice,
                    "runtime_max": profile.runtime_max_sec,
                    "remain_after_exit": profile.remain_after_exit,
                    "collect": profile.collect,
                    "properties": {
                        name: value for name, (_sig, value) in profile.properties.items()
                    },
                }
            )
        )
        return 0

    print(f"name: {profile.name}")
    if profile.description:
        print(f"description: {profile.description}")
    if profile.inherit_env:
        print(f"inherit_env: {', '.join(profile.inherit_env)}")
    if profile.env:
        print("env:")
        for key, value in profile.env.items():
            print(f"  {key}={value}")
    print(
        f"working_directory: {profile.working_directory or '-'} ({profile.working_directory_mode})"
    )
    if profile.unit_type:
        print(f"unit_type: {profile.unit_type}")
    if profile.tags:
        print(f"tags: {', '.join(profile.tags)}")
    if profile.slice_name:
        print(f"slice: {profile.slice_name}")
    if profile.nice is not None:
        print(f"nice: {profile.nice}")
    if profile.runtime_max_sec is not None:
        print(f"runtime_max: {profile.runtime_max_sec}")
    return 0
