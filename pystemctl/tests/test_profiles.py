from __future__ import annotations

import pytest

from pystemctl import profiles
from pystemctl.errors import PystemctlError


def test_resolve_environment_copies_named_vars() -> None:
    profile = profiles.Profile(name="p", inherit_env=("FOO", "MISSING"))
    resolved = profiles.resolve_environment(profile, environ={"FOO": "1"})
    assert resolved == {"FOO": "1"}


def test_resolve_environment_globs() -> None:
    profile = profiles.Profile(name="p", inherit_env=("PYTHON*",))
    resolved = profiles.resolve_environment(profile, environ={"PYTHONPATH": "/x", "OTHER": "y"})
    assert resolved == {"PYTHONPATH": "/x"}


def test_fixed_env_wins_over_inherited() -> None:
    profile = profiles.Profile(name="p", inherit_env=("FOO",), env={"FOO": "fixed"})
    assert profiles.resolve_environment(profile, environ={"FOO": "live"}) == {"FOO": "fixed"}


def test_working_directory_caller_mode() -> None:
    profile = profiles.Profile(name="p", working_directory_mode="caller")
    assert profiles.resolve_working_directory(profile, cwd="/here") == "/here"


def test_working_directory_static_mode() -> None:
    profile = profiles.Profile(name="p", working_directory="/srv", working_directory_mode="static")
    assert profiles.resolve_working_directory(profile, cwd="/here") == "/srv"


def test_apply_cli_overrides_prefers_cli() -> None:
    profile = profiles.Profile(name="p", nice=5, tags=("base",))
    args = type(
        "A",
        (),
        {
            "nice": 10,
            "tags": ["extra"],
            "type": None,
            "description": None,
            "working_directory": None,
            "slice_name": None,
            "runtime_max": None,
        },
    )()
    updated = profiles.apply_cli_overrides(profile, args)
    assert updated.nice == 10
    assert updated.tags == ("base", "extra")


def test_profile_from_table_rejects_unknown_key() -> None:
    from pathlib import Path

    with pytest.raises(PystemctlError):
        profiles._profile_from_table("p", {"nope": 1}, Path("x"))


def test_apply_cli_overrides_is_identity_without_flags() -> None:
    profile = profiles.Profile(name="p", nice=5)
    args = type(
        "A",
        (),
        {
            "nice": None,
            "tags": [],
            "type": None,
            "description": None,
            "working_directory": None,
            "slice_name": None,
            "runtime_max": None,
        },
    )()
    assert profiles.apply_cli_overrides(profile, args) is profile


def test_choose_collect_tagged_job_is_kept() -> None:
    assert profiles.choose_collect(None, ["nix-build"]) is False


def test_choose_collect_untagged_job_is_collected() -> None:
    assert profiles.choose_collect(None, []) is True


def test_choose_collect_explicit_flag_wins() -> None:
    assert profiles.choose_collect(True, ["nix-build"]) is True
    assert profiles.choose_collect(False, []) is False


def test_profile_collect_defaults_to_unset() -> None:
    assert profiles.Profile(name="p").collect is None


def test_profile_collect_can_be_pinned() -> None:
    from pathlib import Path

    profile = profiles._profile_from_table("p", {"collect": False}, Path("x"))
    assert profile.collect is False
