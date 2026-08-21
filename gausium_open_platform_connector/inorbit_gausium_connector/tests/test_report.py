# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest
from inorbit_gausium_connector.src.report import report_time_to_millis
from inorbit_gausium_connector.src.report import report_to_data


@pytest.fixture
def data(task_report):
    return report_to_data(task_report, current_map_name="map1", interruptions_count=0)


def test_areas_and_coverage(data):
    assert data["planned_area_m2"] == 2196.568
    assert data["cleaned_area_m2"] == 659.965
    assert data["coverage_pct"] == 0.3005


def test_durations_are_distinct_whole_seconds(data):
    assert data["duration_s"] == 2941
    assert data["active_cleaning_time_s"] == 2904


def test_efficiency_is_computed_not_taken_from_the_vendor(data):
    assert data["efficiency_m2ph"] == 818.1


def test_efficiency_falls_back_to_the_vendor_value(task_report):
    task_report["durationSeconds"] = 0
    assert report_to_data(task_report)["efficiency_m2ph"] == 870.182


def test_coverage_falls_back_to_completion_percentage(task_report):
    del task_report["plannedCleaningAreaSquareMeter"]
    assert report_to_data(task_report)["coverage_pct"] == 0.3


def test_battery_keys(data):
    assert data["battery_start_pct"] == 1.0
    assert data["battery_end_pct"] == 0.78
    assert data["battery_used_pct"] == pytest.approx(0.22)


def test_battery_used_is_withheld_when_the_robot_charged_mid_task(task_report):
    task_report["startBatteryPercentage"] = 40
    task_report["endBatteryPercentage"] = 90
    data = report_to_data(task_report)

    assert "battery_used_pct" not in data
    assert data["battery_start_pct"] == 0.4
    assert data["battery_end_pct"] == 0.9


def test_consumables_are_residual_percentages(data):
    assert data["consumable_brush_pct"] == 1.0
    assert data["consumable_filter_pct"] == 1.0
    assert data["consumable_suction_blade_pct"] == pytest.approx(0.9118)


def test_identity_and_passthrough_keys(data, task_report):
    assert data["report_id"] == task_report["id"]
    assert data["task_id"] == task_report["taskId"]
    assert data["task_instance_id"] == task_report["taskInstanceId"]
    assert data["task_end_status_raw"] == 1
    assert data["task_progress"] == 0
    assert data["loop_count"] == 0
    assert data["expected_loop_count"] == 0
    assert data["water_used_l"] == 14.611
    assert data["operator"] == "user"
    assert data["report_image_url"] == task_report["taskReportPngUri"]
    assert data["cleaning_mode"] == "scrub"
    assert data["cleaning_mode_raw"] == "洗地"
    assert data["cleaning_mode_label"] == "Wash the floor"


def test_per_map_breakdown(data):
    assert data["map_map1_cleaned_area_m2"] == 659.965
    assert data["floors_cleaned_count"] == 1
    assert data["map_name"] == "map1"


def test_per_map_breakdown_with_two_maps(task_report):
    task_report["subTasks"] = [
        {"mapName": "Floor 1", "actualCleaningAreaSquareMeter": 10.0},
        {"mapName": "Floor 2", "actualCleaningAreaSquareMeter": 20.0},
    ]
    data = report_to_data(task_report)

    assert data["map_floor_1_cleaned_area_m2"] == 10.0
    assert data["map_floor_2_cleaned_area_m2"] == 20.0
    assert data["floors_cleaned_count"] == 2
    assert data["map_name"] == "Floor 1, Floor 2"


def test_colliding_map_slugs_do_not_overwrite(task_report):
    task_report["subTasks"] = [
        {"mapName": "Floor-1", "actualCleaningAreaSquareMeter": 10.0},
        {"mapName": "Floor 1", "actualCleaningAreaSquareMeter": 20.0},
    ]
    data = report_to_data(task_report)

    assert data["map_floor_1_cleaned_area_m2"] == 10.0
    assert data["map_floor_1_2_cleaned_area_m2"] == 20.0


def test_map_name_falls_back_to_the_current_map(task_report):
    task_report["subTasks"] = []
    assert report_to_data(task_report, current_map_name="map1")["map_name"] == "map1"


def test_zero_values_are_kept_and_none_dropped(task_report):
    task_report["waterConsumptionLiter"] = 0.0
    task_report["operator"] = None
    data = report_to_data(task_report, interruptions_count=0)

    assert data["water_used_l"] == 0.0
    assert data["interruptions_count"] == 0
    assert "operator" not in data


def test_report_time_accepts_both_transports():
    assert report_time_to_millis("2026-08-16T11:25:13Z") == 1786879513000
    assert report_time_to_millis(1786879513000) == 1786879513000
    assert report_time_to_millis("") is None
    assert report_time_to_millis(None) is None
