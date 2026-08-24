# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Tests for `gausium_open_platform_connector.src.mission`."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock, Mock

import pytest

from gausium_open_platform_connector.src.canonical import (
    TaskState,
    report_time_to_millis,
)
from gausium_open_platform_connector.src.mission import MissionState, MissionTracker, filter_none

SN = "GS000-0000-000-0001"


@pytest.fixture()
def fetch_reports() -> AsyncMock:
    return AsyncMock(return_value=[])


@pytest.fixture()
def fetch_report_map_images() -> AsyncMock:
    return AsyncMock(return_value=[])


@pytest.fixture()
def publish() -> Mock:
    return Mock()


@pytest.fixture()
def spawned() -> list[asyncio.Task]:
    return []


@pytest.fixture()
def tracker(fetch_reports, fetch_report_map_images, publish, spawned) -> MissionTracker:
    def spawn_task(name: str, coro) -> asyncio.Task:
        task = asyncio.create_task(coro, name=name)
        spawned.append(task)
        return task

    return MissionTracker(
        SN,
        fetch_reports=fetch_reports,
        fetch_report_map_images=fetch_report_map_images,
        publish=publish,
        spawn_task=spawn_task,
        success_threshold=0.90,
    )


@pytest.fixture()
def running_status() -> dict:
    return {
        "executingTask": {
            "id": "task-123",
            "name": "Cleaning Task",
            "progress": 50,
            "timeRemaining": 300,
            "cleaningMileage": 100.5,
        },
        "taskState": TaskState.RUNNING.value,
        "emergencyStop": {"enabled": False},
        "localizationInfo": {
            "map": {"name": "Floor 1", "id": "map-1"},
            "mapPosition": {"x": 10.0, "y": 20.0, "angle": 90.0},
        },
    }


@pytest.fixture()
def running_status_v2() -> dict:
    return {"currentTask": {"taskInstanceId": "task-123", "workMode": {"name": "__洗地"}}}


@pytest.fixture()
def idle_status() -> dict:
    return {"taskState": TaskState.IDLE.value, "emergencyStop": {"enabled": False}}


@pytest.fixture()
def idle_status_v2() -> dict:
    return {"currentTask": {"taskInstanceId": ""}}


@pytest.fixture()
def task_report() -> dict:
    return {
        "id": "report-1",
        "displayName": "clean areas 1 and 2",
        "operator": "user",
        "completionPercentage": 0.917,
        "durationSeconds": 8915,
        "plannedCleaningAreaSquareMeter": 967.26,
        "actualCleaningAreaSquareMeter": 886.918,
        "efficiencySquareMeterPerHour": 999.99,
        "plannedPolishingAreaSquareMeter": 0,
        "actualPolishingAreaSquareMeter": 0,
        "waterConsumptionLiter": 0,
        "startBatteryPercentage": 99,
        "endBatteryPercentage": 49,
        "consumablesResidualPercentage": {"brush": 100, "filter": 100, "suctionBlade": 99.86},
        "taskInstanceId": "task-123",
        "cleaningMode": "洗地",
        "taskEndStatus": 0,
        "taskReportPngUri": "https://example.com/report.png",
        "subTasks": [
            {
                "mapId": "map-1",
                "mapName": "Floor 1",
                "actualCleaningAreaSquareMeter": 886.918,
                "taskId": "task-def-9",
            }
        ],
        "taskId": "task-def-9",
        "planId": "",
        "areaNameList": "",
        "loopCount": 0,
        "expectedLoopCount": 0,
        "taskProgress": 0,
        "startTime": "2026-06-26T03:53:27Z",
        "endTime": "2026-06-26T06:36:50Z",
    }


async def finish_mission(tracker, idle_status, idle_status_v2, spawned) -> None:
    """Feed an idle status to end the running mission and await the completion wait."""
    tracker.update(idle_status, idle_status_v2)
    assert len(spawned) == 1
    await asyncio.gather(*spawned, return_exceptions=True)


@pytest.mark.asyncio
async def test_in_progress_update_publishes_report(
    tracker, publish, running_status, running_status_v2
) -> None:
    tracker.update(running_status, running_status_v2)

    publish.assert_called_once()
    assert publish.call_args[0][0] == {
        "state": "in-progress",
        "status": "OK",
        "inProgress": True,
        "missionId": "task-123",
        "label": "Cleaning Task",
        "completedPercent": 0.5,
        "estimatedDurationSecs": 600,
        "data": {
            "map_name": "Floor 1",
            "task_id": "task-123",
            "task_instance_id": "task-123",
            "distance_m": 100.5,
            "active_cleaning_time_s": 300,
            "task_state": "cleaning",
            "task_state_raw": "RUNNING",
            "interruptions_count": 0,
            "cleaning_mode": "scrub",
            "cleaning_mode_raw": "__洗地",
            "cleaning_mode_label": "Wash the floor",
        },
    }


@pytest.mark.asyncio
async def test_unchanged_status_is_not_republished(
    tracker, publish, running_status, running_status_v2
) -> None:
    tracker.update(running_status, running_status_v2)
    publish.reset_mock()

    tracker.update(running_status, running_status_v2)

    publish.assert_not_called()


@pytest.mark.asyncio
async def test_completed_percent_is_monotonic(
    tracker, publish, running_status, running_status_v2
) -> None:
    tracker.update(running_status, running_status_v2)

    # The robot reports 0 progress when paused; keep the previous progress
    paused_status = deepcopy(running_status)
    paused_status["executingTask"]["progress"] = 0
    paused_status["taskState"] = TaskState.PAUSED.value
    tracker.update(paused_status, running_status_v2)

    report = publish.call_args[0][0]
    assert report["completedPercent"] == 0.5
    assert report["state"] == MissionState.paused.value["state"]
    assert report["status"] == MissionState.paused.value["status"]
    assert report["data"]["task_state"] == "paused"


@pytest.mark.asyncio
async def test_completion_with_successful_report(
    tracker,
    publish,
    fetch_reports,
    spawned,
    running_status,
    running_status_v2,
    idle_status,
    idle_status_v2,
    task_report,
) -> None:
    running_status["executingTask"]["progress"] = 95
    tracker.update(running_status, running_status_v2)
    fetch_reports.return_value = [task_report]

    await finish_mission(tracker, idle_status, idle_status_v2, spawned)

    report = publish.call_args[0][0]
    assert report["state"] == "completed"
    assert report["status"] == "OK"
    assert report["inProgress"] is False
    assert report["label"] == "clean areas 1 and 2"
    # The progress bar shows the covered fraction, not a forced 100%
    assert report["completedPercent"] == 0.9169
    # Wall time, not the vendor's active-cleaning durationSeconds
    assert report["estimatedDurationSecs"] == 9803
    assert report["startTs"] == report_time_to_millis("2026-06-26T03:53:27Z")
    assert report["endTs"] == report_time_to_millis("2026-06-26T06:36:50Z")
    assert report["data"] == {
        "task_outcome": "completed",
        "task_end_status_raw": 0,
        "planned_area_m2": 967.26,
        "cleaned_area_m2": 886.918,
        "coverage_pct": 0.9169,  # Cleaned over planned, not the vendor completionPercentage
        "duration_s": 9803,
        "active_cleaning_time_s": 8915,
        "efficiency_m2ph": 358.1,  # Computed from cleaned area and active time
        "water_used_l": 0,  # Falsy values are kept, only None is filtered
        "battery_start_pct": 99 / 100,
        "battery_end_pct": 49 / 100,
        "battery_used_pct": 50 / 100,
        "interruptions_count": 0,
        "cleaning_mode": "scrub",
        "cleaning_mode_raw": "洗地",
        "cleaning_mode_label": "Wash the floor",
        "task_instance_id": "task-123",
        "task_progress": 0,
        "map_name": "Floor 1",
        "floors_cleaned_count": 1,
        "report_image_url": "https://example.com/report.png",
        "polished_area_planned_m2": 0,
        "polished_area_m2": 0,
        "operator": "user",
        "report_id": "report-1",
        "task_id": "task-def-9",
        "plan_id": "",
        "area_names": "",
        "loop_count": 0,
        "expected_loop_count": 0,
        "consumable_brush_pct": 100 / 100,
        "consumable_filter_pct": 100 / 100,
        "consumable_suction_blade_pct": 99.86 / 100,
        "map_floor_1_cleaned_area_m2": 886.918,
    }


@pytest.mark.asyncio
async def test_completion_below_threshold_is_incomplete(
    tracker,
    publish,
    fetch_reports,
    spawned,
    running_status,
    running_status_v2,
    idle_status,
    idle_status_v2,
    task_report,
) -> None:
    running_status["executingTask"]["progress"] = 95
    tracker.update(running_status, running_status_v2)
    task_report["actualCleaningAreaSquareMeter"] = 400  # Coverage below the 0.90 threshold
    fetch_reports.return_value = [task_report]

    await finish_mission(tracker, idle_status, idle_status_v2, spawned)

    report = publish.call_args[0][0]
    assert report["state"] == MissionState.incomplete.value["state"]
    assert report["status"] == MissionState.incomplete.value["status"]
    assert report["completedPercent"] == report["data"]["coverage_pct"] == 0.4135
    assert report["data"]["task_outcome"] == "incomplete"
    assert "Error" in report["data"]


@pytest.mark.asyncio
@pytest.mark.parametrize("end_status", [1, 2, 3])
async def test_abnormal_end_is_abandoned_regardless_of_coverage(
    tracker,
    publish,
    fetch_reports,
    spawned,
    running_status,
    running_status_v2,
    idle_status,
    idle_status_v2,
    task_report,
    end_status,
) -> None:
    running_status["executingTask"]["progress"] = 95
    tracker.update(running_status, running_status_v2)
    task_report["taskEndStatus"] = end_status
    fetch_reports.return_value = [task_report]

    await finish_mission(tracker, idle_status, idle_status_v2, spawned)

    report = publish.call_args[0][0]
    assert report["state"] == MissionState.abandoned.value["state"]
    assert report["data"]["task_outcome"] == "abandoned"
    assert report["data"]["Error"] == f"Mission ended with task end status {end_status}"


@pytest.mark.asyncio
@pytest.mark.parametrize("end_status", [-1, None], ids=["unknown", "absent"])
async def test_unknown_end_status_falls_back_to_progress_heuristic(
    tracker,
    publish,
    fetch_reports,
    spawned,
    running_status,
    running_status_v2,
    idle_status,
    idle_status_v2,
    task_report,
    end_status,
) -> None:
    # Progress bar never got close to done, so the fallback abandons the mission
    tracker.update(running_status, running_status_v2)
    if end_status is None:
        del task_report["taskEndStatus"]
    else:
        task_report["taskEndStatus"] = end_status
    fetch_reports.return_value = [task_report]

    await finish_mission(tracker, idle_status, idle_status_v2, spawned)

    report = publish.call_args[0][0]
    assert report["state"] == MissionState.abandoned.value["state"]
    assert "task_outcome" not in report["data"]  # Omitted rather than guessed


def test_state_from_end_status_table() -> None:
    state = MissionState.get_from_end_status
    assert state(0, 0.95, 0.90) is MissionState.completed
    assert state(0, 0.5, 0.90) is MissionState.incomplete
    assert state(0, None, 0.90) is MissionState.completed  # Take the robot at its word
    assert state(1, 0.99, 0.90) is MissionState.abandoned
    assert state(2, 0.99, 0.90) is MissionState.abandoned
    assert state(3, 0.99, 0.90) is MissionState.abandoned
    assert state(-1, 0.99, 0.90) is None
    assert state(None, 0.99, 0.90) is None


@pytest.mark.asyncio
async def test_battery_used_withheld_when_charged_mid_task(
    tracker,
    publish,
    fetch_reports,
    spawned,
    running_status,
    running_status_v2,
    idle_status,
    idle_status_v2,
    task_report,
) -> None:
    tracker.update(running_status, running_status_v2)
    task_report["startBatteryPercentage"] = 40
    task_report["endBatteryPercentage"] = 90
    fetch_reports.return_value = [task_report]

    await finish_mission(tracker, idle_status, idle_status_v2, spawned)

    data = publish.call_args[0][0]["data"]
    assert data["battery_start_pct"] == 40 / 100
    assert data["battery_end_pct"] == 90 / 100
    assert "battery_used_pct" not in data


@pytest.mark.asyncio
async def test_coverage_heatmap_urls_joined_in_vendor_order(
    tracker,
    publish,
    fetch_reports,
    fetch_report_map_images,
    spawned,
    running_status,
    running_status_v2,
    idle_status,
    idle_status_v2,
    task_report,
) -> None:
    tracker.update(running_status, running_status_v2)
    fetch_reports.return_value = [task_report]
    fetch_report_map_images.return_value = [
        {"url": "https://example.com/1", "map_image_id": 1},
        {"url": "https://example.com/0", "map_image_id": 0},
    ]

    await finish_mission(tracker, idle_status, idle_status_v2, spawned)

    fetch_report_map_images.assert_awaited_once_with("report-1")
    data = publish.call_args[0][0]["data"]
    assert data["coverage_heatmap_url"] == "https://example.com/0, https://example.com/1"


@pytest.mark.asyncio
async def test_no_map_images_yields_no_heatmap_key(
    tracker,
    publish,
    fetch_reports,
    fetch_report_map_images,
    spawned,
    running_status,
    running_status_v2,
    idle_status,
    idle_status_v2,
    task_report,
) -> None:
    tracker.update(running_status, running_status_v2)
    fetch_reports.return_value = [task_report]
    fetch_report_map_images.return_value = None  # API failure must not break completion

    await finish_mission(tracker, idle_status, idle_status_v2, spawned)

    assert "coverage_heatmap_url" not in publish.call_args[0][0]["data"]


@pytest.mark.asyncio
async def test_multi_map_report_breakdown(
    tracker,
    publish,
    fetch_reports,
    spawned,
    running_status,
    running_status_v2,
    idle_status,
    idle_status_v2,
    task_report,
) -> None:
    tracker.update(running_status, running_status_v2)
    task_report["subTasks"] = [
        {"mapName": "Floor 1", "actualCleaningAreaSquareMeter": 100.0},
        {"mapName": "Floor 2", "actualCleaningAreaSquareMeter": 200.0},
        {"mapName": "Floor 2", "actualCleaningAreaSquareMeter": 50.0},  # Slug collision
    ]
    fetch_reports.return_value = [task_report]

    await finish_mission(tracker, idle_status, idle_status_v2, spawned)

    data = publish.call_args[0][0]["data"]
    assert data["map_name"] == "Floor 1, Floor 2"
    assert data["floors_cleaned_count"] == 3
    assert data["map_floor_1_cleaned_area_m2"] == 100.0
    assert data["map_floor_2_cleaned_area_m2"] == 200.0
    assert data["map_floor_2_2_cleaned_area_m2"] == 50.0


@pytest.mark.asyncio
async def test_interruptions_counted_and_reset(
    tracker, publish, spawned, running_status, running_status_v2
) -> None:
    tracker.update(running_status, running_status_v2)

    paused_status = deepcopy(running_status)
    paused_status["taskState"] = TaskState.PAUSED.value
    tracker.update(paused_status, running_status_v2)
    resumed_status = deepcopy(running_status)
    resumed_status["executingTask"]["progress"] = 60
    tracker.update(resumed_status, running_status_v2)
    tracker.update(paused_status, running_status_v2)

    assert publish.call_args[0][0]["data"]["interruptions_count"] == 2

    # A new task instance starts the counter fresh
    next_status = deepcopy(running_status)
    next_status["executingTask"]["id"] = "task-456"
    tracker.update(next_status, {"currentTask": {"taskInstanceId": "task-456"}})

    assert publish.call_args[0][0]["data"]["interruptions_count"] == 0
    for task in spawned:
        task.cancel()
    await asyncio.gather(*spawned, return_exceptions=True)


@pytest.mark.asyncio
async def test_completed_report_carries_interruptions(
    tracker,
    publish,
    fetch_reports,
    spawned,
    running_status,
    running_status_v2,
    idle_status,
    idle_status_v2,
    task_report,
) -> None:
    tracker.update(running_status, running_status_v2)
    paused_status = deepcopy(running_status)
    paused_status["taskState"] = TaskState.PAUSED.value
    tracker.update(paused_status, running_status_v2)
    fetch_reports.return_value = [task_report]

    await finish_mission(tracker, idle_status, idle_status_v2, spawned)

    assert publish.call_args[0][0]["data"]["interruptions_count"] == 1


@pytest.mark.asyncio
async def test_push_transport_epoch_millis_timestamps(
    tracker,
    publish,
    fetch_reports,
    spawned,
    running_status,
    running_status_v2,
    idle_status,
    idle_status_v2,
    task_report,
) -> None:
    # The push callback sends epoch milliseconds instead of ISO 8601 strings
    task_report["startTime"] = 1750912000000
    task_report["endTime"] = 1750912060000
    fetch_reports.return_value = [task_report]
    tracker.update(running_status, running_status_v2)

    await finish_mission(tracker, idle_status, idle_status_v2, spawned)

    report = publish.call_args[0][0]
    assert report["startTs"] == 1750912000000
    assert report["endTs"] == 1750912060000
    assert report["data"]["duration_s"] == 60


@pytest.mark.asyncio
async def test_completion_report_not_found(
    monkeypatch,
    tracker,
    publish,
    fetch_reports,
    spawned,
    running_status,
    running_status_v2,
    idle_status,
    idle_status_v2,
) -> None:
    monkeypatch.setattr(
        "gausium_open_platform_connector.src.mission.MAX_TASK_REPORT_WAIT_TIME_SECS", 0.1
    )
    tracker.update(running_status, running_status_v2)
    fetch_reports.return_value = [{"id": "other", "taskInstanceId": "task-other"}]

    await finish_mission(tracker, idle_status, idle_status_v2, spawned)

    report = publish.call_args[0][0]
    assert report["state"] == MissionState.not_reported.value["state"]
    assert report["status"] == MissionState.not_reported.value["status"]
    assert report["inProgress"] is False
    assert report["data"] == {"Error": "Unable to find task report."}


@pytest.mark.asyncio
async def test_task_resumed_cancels_completion_wait(
    tracker, publish, spawned, running_status, running_status_v2, idle_status, idle_status_v2
) -> None:
    tracker.update(running_status, running_status_v2)
    publish.reset_mock()

    # Mission appears to end; a completion wait starts polling (empty reports)
    tracker.update(idle_status, idle_status_v2)
    assert "task-123" in tracker._pending_completion_tasks
    await asyncio.sleep(0)

    # The same task resumes: the wait is cancelled and no final report is published
    resumed_status = deepcopy(running_status)
    resumed_status["executingTask"]["progress"] = 60
    tracker.update(resumed_status, running_status_v2)
    await asyncio.gather(*spawned, return_exceptions=True)

    assert tracker._pending_completion_tasks == {}
    reports = [call.args[0] for call in publish.call_args_list]
    assert all(report["inProgress"] for report in reports)


@pytest.mark.asyncio
async def test_disagreement_window_keeps_completion_wait(
    tracker, running_status, running_status_v2, idle_status
) -> None:
    """While v1 has dropped executingTask but v2 still reports the task, the wait persists."""
    tracker.update(running_status, running_status_v2)

    tracker.update(idle_status, running_status_v2)
    wait_task = tracker._pending_completion_tasks["task-123"]

    tracker.update(idle_status, running_status_v2)
    tracker.update(idle_status, running_status_v2)

    assert tracker._pending_completion_tasks["task-123"] is wait_task
    assert not wait_task.cancelled()
    wait_task.cancel()
    await asyncio.gather(wait_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_next_mission_progress_starts_fresh(
    tracker, publish, spawned, running_status, running_status_v2, idle_status, idle_status_v2
) -> None:
    """A new mission must not inherit the previous mission's completedPercent."""
    running_status["executingTask"]["progress"] = 97
    tracker.update(running_status, running_status_v2)
    tracker.update(idle_status, idle_status_v2)
    publish.reset_mock()

    next_status = deepcopy(running_status)
    next_status["executingTask"]["id"] = "task-456"
    next_status["executingTask"]["progress"] = 5
    tracker.update(next_status, {"currentTask": {"taskInstanceId": "task-456"}})

    assert publish.call_args[0][0]["completedPercent"] == 0.05
    for task in spawned:
        task.cancel()
    await asyncio.gather(*spawned, return_exceptions=True)


@pytest.mark.asyncio
async def test_shutdown_cancels_pending_waits(
    tracker, spawned, running_status, running_status_v2, idle_status, idle_status_v2
) -> None:
    tracker.update(running_status, running_status_v2)
    tracker.update(idle_status, idle_status_v2)
    assert len(spawned) == 1

    await tracker.shutdown()

    assert tracker._pending_completion_tasks == {}
    assert tracker._shutdown_event.is_set()
    assert spawned[0].done()


def test_filter_none() -> None:
    data = {"valid": "value", "empty": "", "none": None, "zero": 0, "false": False, "true": True}
    assert filter_none(data) == {
        "valid": "value",
        "empty": "",
        "zero": 0,
        "false": False,
        "true": True,
    }
