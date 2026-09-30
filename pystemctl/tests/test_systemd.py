from __future__ import annotations

from pystemctl.systemd import generate_unit_name, normalize_unit_name


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
