# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Tests for `gausium_open_platform_connector.src.key_values`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gausium_open_platform_connector.src.key_values import build_key_values, derive_mission_status

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture()
def status_v1() -> dict:
    return load_fixture("status_v1.json")


@pytest.fixture()
def status_v2() -> dict:
    return load_fixture("status_v2.json")


def test_full_key_value_set(status_v1, status_v2) -> None:
    assert build_key_values(status_v1, status_v2) == {
        "battery_pct": 1.0,
        "charging": False,
        "task_state": "idle",
        "task_state_raw": "IDLE",
        "robot_online": True,
        "current_map_name": "floor_1",
        "clean_water_tank_pct": 0.6,
        "recovery_tank_pct": 0.0,
        "emergency_stop": False,
        "speed_kmph": 0,
        "mission_status": "Idle",
        "localization_state": "LOST",
        "nav_status": "NAVI_IDLE",
        "elevator_status": "ELEVATOR_CONTROLLER_IDLE",
        "manual_control": False,
        "battery_soh": "HEALTHY",
        "battery_cycles": 9,
        "battery_temp_c": 27,
        "spray_active": False,
        "spray_water_level": 0,
        "vacuum_active": False,
        "vacuum_level": 0,
        "filter_active": False,
        "scrubber_brush_active": False,
        "scrubber_brush_down": False,
        "soft_squeegee_down": False,
        "rolling_squeegee_down": False,
        "side_brush_left_down": False,
        "side_brush_right_down": False,
        "executable_tasks": [
            {"id": "task-def-1", "name": "Daily_Clean", "map_name": "floor_1"},
            {"id": "task-def-2", "name": "Weekly_Clean", "map_name": "floor_1"},
        ],
        "nav_points": ["Maintenance"],
        "work_modes": [
            {"id": "mode-1", "name": "__尘推", "strength": "custom", "type": "1"},
            {"id": "mode-2", "name": "__洗地", "strength": "custom", "type": "1"},
            {"id": "inspect", "name": "inspect", "strength": "middle", "type": "5"},
        ],
        "consumable_rolling_brush_wear_pct": 0.0,
        "consumable_scrubber_brush_wear_pct": 0.0,
        "consumable_soft_squeegee_wear_pct": 22.106201 / 250,
        "consumable_rolling_squeegee_wear_pct": 0.0,
        "consumable_ordinary_dust_push_wear_pct": 0.0,
        "consumable_rolling_dust_push_wear_pct": 0.0,
        "consumable_filter_wear_pct": 0.0,
    }


@pytest.mark.parametrize(
    ("vendor_state", "canonical"),
    [
        ("IDLE", "idle"),
        ("RUNNING", "cleaning"),
        ("PAUSED", "paused"),
        ("OTHER", "unknown"),
        ("SOMETHING_NEW", "unknown"),
    ],
)
def test_task_state_normalization(status_v1, status_v2, vendor_state, canonical) -> None:
    status_v1["taskState"] = vendor_state

    key_values = build_key_values(status_v1, status_v2)

    assert key_values["task_state"] == canonical
    assert key_values["task_state_raw"] == vendor_state


def test_task_state_absent_omits_keys(status_v1, status_v2) -> None:
    del status_v1["taskState"]

    key_values = build_key_values(status_v1, status_v2)

    assert "task_state" not in key_values
    assert "task_state_raw" not in key_values
    assert "mission_status" not in key_values


# --- mission_status precedence: Error > Mission > Charging > Idle ----------------


def test_mission_status_emergency_stop_is_error(status_v1, status_v2) -> None:
    status_v1["emergencyStop"]["enabled"] = True
    status_v1["taskState"] = "RUNNING"

    assert derive_mission_status(status_v1, status_v2) == "Error"


@pytest.mark.parametrize("vendor_state", ["RUNNING", "PAUSED", "OTHER"])
def test_mission_status_active_states_are_mission(status_v1, status_v2, vendor_state) -> None:
    # No fifth Paused value: a paused task stays Mission, visible via task_state
    status_v1["taskState"] = vendor_state

    assert derive_mission_status(status_v1, status_v2) == "Mission"


def test_mission_status_v2_task_makes_idle_a_mission(status_v1, status_v2) -> None:
    status_v2["currentTask"]["taskInstanceId"] = "task-instance-1"

    assert derive_mission_status(status_v1, status_v2) == "Mission"


def test_mission_status_mission_outranks_charging(status_v1, status_v2) -> None:
    status_v1["taskState"] = "RUNNING"
    status_v1["battery"]["charging"] = True

    assert derive_mission_status(status_v1, status_v2) == "Mission"


def test_mission_status_charging(status_v1, status_v2) -> None:
    status_v1["battery"]["charging"] = True

    assert derive_mission_status(status_v1, status_v2) == "Charging"


def test_mission_status_idle_and_lost_is_idle(status_v1, status_v2) -> None:
    # LOST fires continuously on healthy parked robots, so it never maps to Error
    assert status_v1["localizationInfo"]["localizationState"] == "LOST"

    assert derive_mission_status(status_v1, status_v2) == "Idle"


def test_mission_status_absent_task_state_is_omitted(status_v1, status_v2) -> None:
    del status_v1["taskState"]
    status_v1["emergencyStop"]["enabled"] = True

    assert derive_mission_status(status_v1, status_v2) is None


# --- Field-level behaviors -----------------------------------------------------


def test_negative_levels_are_absent(status_v1, status_v2) -> None:
    # -1 means not available
    status_v1["device"]["spray"]["waterLevel"] = -1
    status_v2["device"]["vacuum"]["level"] = -1

    key_values = build_key_values(status_v1, status_v2)

    assert "spray_water_level" not in key_values
    assert "vacuum_level" not in key_values


def test_consumable_wear_is_generic_and_clamped(status_v1, status_v2) -> None:
    # Parts only present in the v2 payload are picked up by the same rule
    status_v2["device"]["hepaSensor"] = {"lifeSpan": 100, "usedLife": 150}
    del status_v1["device"]["rollingBrush"]
    del status_v2["device"]["rollingBrush"]

    key_values = build_key_values(status_v1, status_v2)

    assert key_values["consumable_hepa_sensor_wear_pct"] == 1.0  # Clamped
    assert "consumable_rolling_brush_wear_pct" not in key_values
    # Parts without a life span generate no key
    assert "consumable_left_side_brush_wear_pct" not in key_values


def test_cleaning_mode_present_only_while_a_task_runs(status_v1, status_v2) -> None:
    idle_key_values = build_key_values(status_v1, status_v2)
    assert "cleaning_mode" not in idle_key_values

    status_v2["currentTask"]["workMode"]["name"] = "__洗地"
    running_key_values = build_key_values(status_v1, status_v2)

    assert running_key_values["cleaning_mode"] == "scrub"
    assert running_key_values["cleaning_mode_raw"] == "__洗地"


def test_unknown_cleaning_mode_is_other_with_raw_preserved(status_v1, status_v2) -> None:
    status_v2["currentTask"]["workMode"]["name"] = "重度清洁"

    key_values = build_key_values(status_v1, status_v2)

    assert key_values["cleaning_mode"] == "other"
    assert key_values["cleaning_mode_raw"] == "重度清洁"


def test_empty_payloads_yield_no_keys(status_v2) -> None:
    assert build_key_values({}, {}) == {}
    # A v2-only tick still yields the v2-sourced keys and nothing else
    key_values = build_key_values({}, status_v2)
    assert key_values["manual_control"] is False
    assert "battery_pct" not in key_values
