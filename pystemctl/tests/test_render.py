from __future__ import annotations

import datetime as dt

from pystemctl.render import format_duration, format_property_value, format_table


def test_format_duration() -> None:
    assert format_duration(dt.timedelta(seconds=3661)) == "1h 1min"
    assert format_duration(dt.timedelta(seconds=5)) == "5s"
    assert format_duration(dt.timedelta(seconds=90061)) == "1d 1h"


def test_format_table_pads_columns() -> None:
    table = format_table(["A", "BB"], [["x", "y"]])
    assert table == "A  BB\nx  y"


def test_format_property_value() -> None:
    assert format_property_value(True) == "yes"
    assert format_property_value(False) == "no"
    assert format_property_value(["a", "b"]) == "a b"
    assert format_property_value(7) == "7"
