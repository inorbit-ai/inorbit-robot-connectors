# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest
from inorbit_gausium_connector.src.canonical import camel_to_snake
from inorbit_gausium_connector.src.canonical import cleaning_mode_keys
from inorbit_gausium_connector.src.canonical import normalize_task_state
from inorbit_gausium_connector.src.canonical import pct
from inorbit_gausium_connector.src.canonical import slug


@pytest.mark.parametrize(
    "vendor, expected",
    [
        ("IDLE", "idle"),
        ("RUNNING", "cleaning"),
        ("PAUSED", "paused"),
        ("OTHER", "unknown"),
        ("SOMETHING_NEW", "unknown"),
        (None, "unknown"),
    ],
)
def test_normalize_task_state(vendor, expected):
    assert normalize_task_state(vendor) == expected


@pytest.mark.parametrize(
    "vendor, expected",
    [
        ("洗地", "scrub"),
        ("滚刷洗地", "scrub"),
        ("尘推", "dust_mop"),
        ("快速尘推", "dust_mop"),
        ("低速尘推", "dust_mop"),
        ("静音推尘", "dust_mop"),
        ("布刷尘推", "dust_mop"),
        ("抛光", "polish"),
        ("深度抛光", "polish"),
        ("结晶模式", "polish"),
        ("吸尘", "vacuum"),
        ("吸风清洁", "vacuum"),
        ("suction_cleaning", "vacuum"),
        ("扫地", "sweep"),
        ("喷雾消毒", "disinfect"),
        ("地毯清洁", "other"),
        ("轻度清洁", "other"),
        ("middle_cleaning", "other"),
        ("测试", "other"),
    ],
)
def test_cleaning_mode_enum(vendor, expected):
    assert cleaning_mode_keys(vendor)["cleaning_mode"] == expected
    assert cleaning_mode_keys(f"__{vendor}")["cleaning_mode"] == expected


def test_cleaning_mode_keys_publish_enum_raw_and_label():
    assert cleaning_mode_keys("__洗地") == {
        "cleaning_mode": "scrub",
        "cleaning_mode_raw": "__洗地",
        "cleaning_mode_label": "Wash the floor",
    }


def test_cleaning_mode_label_falls_back_to_the_stripped_vendor_value():
    keys = cleaning_mode_keys("__未知模式")

    assert keys["cleaning_mode"] == "other"
    assert keys["cleaning_mode_raw"] == "__未知模式"
    assert keys["cleaning_mode_label"] == "未知模式"


def test_cleaning_mode_labels_are_spelled_out():
    assert cleaning_mode_keys("静音推尘")["cleaning_mode_label"] == "Silent dust mopping"


def test_cleaning_mode_keys_without_a_value():
    assert cleaning_mode_keys("") == {}
    assert cleaning_mode_keys(None) == {}


def test_pct_converts_and_ignores_non_numbers():
    assert pct(60) == 0.6
    assert pct(0) == 0.0
    assert pct(None) is None
    assert pct(True) is None


def test_slug_and_camel_to_snake():
    assert slug("Main Floor #2") == "main_floor_2"
    assert slug("--map1--") == "map1"
    assert camel_to_snake("softSqueegee") == "soft_squeegee"
    assert camel_to_snake("cleanWaterFilter") == "clean_water_filter"
