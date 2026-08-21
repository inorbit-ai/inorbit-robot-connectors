# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest
from inorbit_gausium_connector.src.key_values import build_key_values


@pytest.fixture
def key_values(status_v1, status_v2):
    return build_key_values(status_v1, status_v2, {"displayName": "robot1"}, True, "9.9.9")


def test_contract_keys(key_values):
    assert key_values["battery_pct"] == 1.0
    assert key_values["charging"] is False
    assert key_values["task_state"] == "idle"
    assert key_values["task_state_raw"] == "IDLE"
    assert key_values["robot_online"] is True
    assert key_values["current_map_name"] == "map1"
    assert key_values["clean_water_tank_pct"] == 0.6
    assert key_values["recovery_tank_pct"] == 0.0
    assert key_values["emergency_stop"] is False
    assert key_values["speed_kmph"] == 0
    assert key_values["mission_status"] == "Idle"


def test_additional_keys(key_values):
    assert key_values["localization_state"] == "LOST"
    assert key_values["nav_status"] == "NAVI_IDLE"
    assert key_values["elevator_status"] == "ELEVATOR_CONTROLLER_IDLE"
    assert key_values["manual_control"] is False
    assert key_values["battery_soh"] == "HEALTHY"
    assert key_values["battery_cycles"] == 9
    assert key_values["battery_temp_c"] == 27
    assert key_values["nav_points"] == ["Maintenance"]
    assert key_values["executable_tasks"][0]["map_name"] == "map1"
    assert {"id", "name", "map_name"} == set(key_values["executable_tasks"][0])
    assert key_values["work_modes"][0]["strength"] == "custom"


def test_work_modes_carry_only_the_contract_fields(status_v1, status_v2):
    status_v1["workModes"] = [
        {"id": "1", "name": "__洗地", "strength": "custom", "type": "1", "subType": "surprise"}
    ]
    key_values = build_key_values(status_v1, status_v2, {}, True, "9.9.9")

    assert key_values["work_modes"] == [
        {"id": "1", "name": "__洗地", "strength": "custom", "type": "1"}
    ]


def test_work_modes_omitted_when_neither_payload_reports_them(status_v1, status_v2):
    del status_v1["workModes"]
    del status_v2["workModes"]

    assert "work_modes" not in build_key_values(status_v1, status_v2, {}, True, "9.9.9")


def test_actuator_flags_are_booleans(key_values):
    for key in (
        "spray_active",
        "vacuum_active",
        "filter_active",
        "scrubber_brush_active",
        "scrubber_brush_down",
        "soft_squeegee_down",
        "rolling_squeegee_down",
        "side_brush_left_down",
        "side_brush_right_down",
    ):
        assert key_values[key] is False


def test_unavailable_levels_are_omitted(status_v1, status_v2):
    status_v1["device"]["spray"]["waterLevel"] = -1
    status_v2["device"]["vacuum"]["level"] = -1
    key_values = build_key_values(status_v1, status_v2, {}, True, "9.9.9")

    assert "spray_water_level" not in key_values
    assert "vacuum_level" not in key_values


def test_consumable_wear_is_generated_per_part(key_values):
    wear = {k: v for k, v in key_values.items() if k.startswith("consumable_")}

    assert len(wear) == 7
    assert wear["consumable_soft_squeegee_wear_pct"] == pytest.approx(0.0884248)
    assert wear["consumable_rolling_brush_wear_pct"] == 0.0
    assert "consumable_left_side_brush_wear_pct" not in wear


def test_consumable_wear_is_clamped(status_v1, status_v2):
    status_v1["device"]["filter"]["usedLife"] = 500
    key_values = build_key_values(status_v1, status_v2, {}, True, "9.9.9")

    assert key_values["consumable_filter_wear_pct"] == 1.0


def test_cleaning_mode_published_only_while_a_task_runs(key_values, status_v1, status_v2):
    assert "cleaning_mode" not in key_values

    status_v2["currentTask"]["workMode"]["name"] = "__洗地"
    running = build_key_values(status_v1, status_v2, {}, True, "9.9.9")

    assert running["cleaning_mode"] == "scrub"
    assert running["cleaning_mode_raw"] == "__洗地"
    assert running["cleaning_mode_label"] == "Wash the floor"


def test_metadata_keys(key_values):
    assert key_values["api_connected"] is True
    assert key_values["connector_version"] == "9.9.9"
    assert key_values["display_name"] == "robot1"


def test_no_vendor_blob_leaks(key_values):
    assert "localizationInfo" not in key_values
    assert "battery" not in key_values
    assert "device" not in key_values
    assert "battery_percentage" not in key_values
    assert "total_traveled_distance" not in key_values


@pytest.mark.parametrize(
    "task_state, emergency_stop, charging, task_instance_id, expected",
    [
        ("IDLE", True, False, "", "Error"),
        ("RUNNING", True, False, "", "Error"),
        ("RUNNING", False, False, "", "Mission"),
        ("PAUSED", False, False, "", "Mission"),
        ("OTHER", False, False, "", "Mission"),
        ("RUNNING", False, True, "", "Mission"),
        ("IDLE", False, False, "abc", "Mission"),
        ("IDLE", False, True, "", "Charging"),
        ("IDLE", False, False, "", "Idle"),
    ],
)
def test_mission_status_precedence(
    status_v1, status_v2, task_state, emergency_stop, charging, task_instance_id, expected
):
    status_v1["taskState"] = task_state
    status_v1["emergencyStop"]["enabled"] = emergency_stop
    status_v1["battery"]["charging"] = charging
    status_v2["currentTask"]["taskInstanceId"] = task_instance_id

    assert build_key_values(status_v1, status_v2, {}, True, "9.9.9")["mission_status"] == expected


def test_mission_status_ignores_lost_localization(key_values):
    assert key_values["localization_state"] == "LOST"
    assert key_values["mission_status"] == "Idle"


def test_mission_status_omitted_without_a_task_state(status_v1, status_v2):
    del status_v1["taskState"]
    key_values = build_key_values(status_v1, status_v2, {}, True, "9.9.9")

    assert "mission_status" not in key_values
    assert "task_state" not in key_values
    assert "task_state_raw" not in key_values
