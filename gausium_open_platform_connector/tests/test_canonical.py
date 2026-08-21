# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Tests for `gausium_open_platform_connector.src.canonical`."""

from __future__ import annotations

from datetime import datetime

from gausium_open_platform_connector.src.canonical import (
    camel_to_snake,
    cleaning_mode_keys,
    normalize_task_state,
    pct,
    slug,
)
from gausium_open_platform_connector.src.report import report_time_to_millis


def test_normalize_task_state() -> None:
    assert normalize_task_state("IDLE") == "idle"
    assert normalize_task_state("RUNNING") == "cleaning"
    assert normalize_task_state("PAUSED") == "paused"
    assert normalize_task_state("OTHER") == "unknown"
    assert normalize_task_state("SOMETHING_NEW") == "unknown"


def test_cleaning_mode_keys() -> None:
    # Vendor names carry leading underscores in the status payloads and none in reports
    assert cleaning_mode_keys("__洗地") == {
        "cleaning_mode": "scrub",
        "cleaning_mode_raw": "__洗地",
        "cleaning_mode_label": "Wash the floor",
    }
    assert cleaning_mode_keys("洗地")["cleaning_mode"] == "scrub"
    assert cleaning_mode_keys("尘推")["cleaning_mode"] == "dust_mop"
    assert cleaning_mode_keys("抛光")["cleaning_mode"] == "polish"
    assert cleaning_mode_keys("吸尘")["cleaning_mode"] == "vacuum"
    assert cleaning_mode_keys("扫地")["cleaning_mode"] == "sweep"
    assert cleaning_mode_keys("喷雾消毒")["cleaning_mode"] == "disinfect"
    # Underscores inside the name survive, so suction_cleaning stays mappable
    assert cleaning_mode_keys("suction_cleaning")["cleaning_mode"] == "vacuum"
    # Intensity variants are not guessed into a category
    assert cleaning_mode_keys("重度清洁")["cleaning_mode"] == "other"
    # An unknown mode keeps the vendor value as its own label
    assert cleaning_mode_keys("未知模式") == {
        "cleaning_mode": "other",
        "cleaning_mode_raw": "未知模式",
        "cleaning_mode_label": "未知模式",
    }
    assert cleaning_mode_keys("静音推尘")["cleaning_mode_label"] == "Silent dust mopping"
    assert cleaning_mode_keys("") == {}
    assert cleaning_mode_keys(None) == {}


def test_pct() -> None:
    assert pct(50) == 0.5
    assert pct(0) == 0.0
    assert pct(None) is None
    # Booleans are ints in Python, and a flag is not a percentage
    assert pct(True) is None
    assert pct("50") is None


def test_slug_and_camel_to_snake() -> None:
    assert slug("Main Floor #2") == "main_floor_2"
    assert slug("Floor 1") == "floor_1"
    assert camel_to_snake("softSqueegee") == "soft_squeegee"
    assert camel_to_snake("filter") == "filter"


def test_report_time_to_millis() -> None:
    expected = int(datetime.fromisoformat("2026-06-26T03:53:27Z").timestamp() * 1000)
    assert report_time_to_millis("2026-06-26T03:53:27Z") == expected
    # The report push callback sends epoch milliseconds, as a number or a string
    assert report_time_to_millis(1750912000000) == 1750912000000
    assert report_time_to_millis("1750912000000") == 1750912000000
    assert report_time_to_millis(None) is None
    assert report_time_to_millis("") is None
