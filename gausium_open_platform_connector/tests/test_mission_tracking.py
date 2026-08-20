# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Tests for `gausium_open_platform_connector.src.mission`."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime
from unittest.mock import AsyncMock, Mock

import pytest

from gausium_open_platform_connector.src.mission import (
    MissionState,
    MissionTracker,
    TaskState,
    filter_truthy,
    gausium_date_to_inorbit_millis,
)

SN = "GS000-0000-000-0001"


@pytest.fixture()
def fetch_reports() -> AsyncMock:
    return AsyncMock(return_value=[])


@pytest.fixture()
def publish() -> Mock:
    return Mock()


@pytest.fixture()
def spawned() -> list[asyncio.Task]:
    return []


@pytest.fixture()
def tracker(fetch_reports, publish, spawned) -> MissionTracker:
    def spawn_task(name: str, coro) -> asyncio.Task:
        task = asyncio.create_task(coro, name=name)
        spawned.append(task)
        return task

    return MissionTracker(
        SN,
        fetch_reports=fetch_reports,
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
    return {"currentTask": {"taskInstanceId": "task-123"}}


@pytest.fixture()
def idle_status() -> dict:
    return {"taskState": TaskState.IDLE.value, "emergencyStop": {"enabled": False}}


@pytest.fixture()
def idle_status_v2() -> dict:
    return {"currentTask": {"taskInstanceId": ""}}


@pytest.fixture()
def task_report() -> dict:
    return {
        "id": "9ef6801e-457f-45e5-bfce-46a44db05e4e",
        "displayName": "clean areas 1 and 2",
        "operator": "user",
        "completionPercentage": 0.917,
        "durationSeconds": 8915,
        "plannedCleaningAreaSquareMeter": 967.26,
        "actualCleaningAreaSquareMeter": 886.918,
        "efficiencySquareMeterPerHour": 358.15,
        "waterConsumptionLiter": 0,
        "startBatteryPercentage": 99,
        "endBatteryPercentage": 49,
        "consumablesResidualPercentage": {"brush": 100, "filter": 100, "suctionBlade": 99.86},
        "taskInstanceId": "task-123",
        "cleaningMode": "洗地",
        "taskReportPngUri": "https://example.com/report.png",
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
            "Map name": "Floor 1",
            "Task ID": "task-123",
            "Task instance ID": "task-123",
            "Task state": TaskState.RUNNING.value,
            "Cleaning mileage": 100.5,
            "Time elapsed [s]": 300,
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
    assert report["completedPercent"] == 1
    assert report["estimatedDurationSecs"] == 8915
    assert report["startTs"] == gausium_date_to_inorbit_millis("2026-06-26T03:53:27Z")
    assert report["endTs"] == gausium_date_to_inorbit_millis("2026-06-26T06:36:50Z")
    assert report["data"]["Report image URI"] == "https://example.com/report.png"
    assert report["data"]["Cleaning mode"] == "Wash the floor"
    assert "Task state" not in report["data"]  # Reset (and filtered) when the mission ends


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
    task_report["completionPercentage"] = 0.5  # Below the 0.90 success threshold
    fetch_reports.return_value = [task_report]

    await finish_mission(tracker, idle_status, idle_status_v2, spawned)

    report = publish.call_args[0][0]
    assert report["state"] == MissionState.incomplete.value["state"]
    assert report["status"] == MissionState.incomplete.value["status"]
    assert report["completedPercent"] == 1
    assert "Error" in report["data"]


@pytest.mark.asyncio
async def test_completion_with_low_progress_is_abandoned(
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
    # Progress bar never got close to done
    tracker.update(running_status, running_status_v2)
    fetch_reports.return_value = [task_report]

    await finish_mission(tracker, idle_status, idle_status_v2, spawned)

    report = publish.call_args[0][0]
    assert report["state"] == MissionState.abandoned.value["state"]
    assert report["status"] == MissionState.abandoned.value["status"]
    assert report["completedPercent"] == 0.5


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
    assert report["data"] == {"Error": "Unable to find task report.", "Task state": None}


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


def test_filter_truthy() -> None:
    data = {"valid": "value", "empty": "", "none": None, "zero": 0, "false": False, "true": True}
    assert filter_truthy(data) == {"valid": "value", "true": True}


def test_gausium_date_to_inorbit_millis() -> None:
    expected = int(datetime.fromisoformat("2026-06-26T03:53:27+00:00").timestamp() * 1000)
    assert gausium_date_to_inorbit_millis("2026-06-26T03:53:27Z") == expected


def test_translate_cleaning_mode() -> None:
    assert MissionTracker._translate_cleaning_mode("__洗地") == "Wash the floor"
    assert MissionTracker._translate_cleaning_mode("尘推") == "Dust mop"
    assert MissionTracker._translate_cleaning_mode("未知模式") == "未知模式"
    assert MissionTracker._translate_cleaning_mode("") == ""
