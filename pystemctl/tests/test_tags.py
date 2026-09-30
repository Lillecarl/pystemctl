from __future__ import annotations

from pystemctl.systemd.tags import (
    environment_to_tags,
    matches,
    read_tags,
    session_id,
    tags_to_environment,
)


def test_tags_round_trip() -> None:
    assert environment_to_tags(tags_to_environment(["a", "b"])) == ["a", "b"]


def test_tags_deduplicate_and_strip() -> None:
    assert tags_to_environment([" a ", "a", "", "b"]) == "a,b"


def test_read_tags_and_session() -> None:
    tags, session = read_tags({"PYSTEMCTL_TAGS": "x,y", "PYSTEMCTL_SESSION": "s1"})
    assert tags == ["x", "y"]
    assert session == "s1"


def test_read_tags_missing() -> None:
    assert read_tags({}) == ([], None)


def test_matches_requires_every_tag() -> None:
    env = {"PYSTEMCTL_TAGS": "a,b", "PYSTEMCTL_SESSION": "s1"}
    assert matches(env, required_tags=["a"])
    assert matches(env, required_tags=["a", "b"], session="s1")
    assert not matches(env, required_tags=["c"])
    assert not matches(env, session="other")


def test_session_id_from_environment(monkeypatch: object) -> None:
    import os

    os.environ["OPENCODE_SESSION_ID"] = "abc"
    try:
        assert session_id() == "abc"
    finally:
        del os.environ["OPENCODE_SESSION_ID"]
