# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Canonical live key-values built from the v1 and v2 status payloads."""

from typing import Any

from .canonical import camel_to_snake
from .canonical import cleaning_mode_keys
from .canonical import normalize_task_state
from .canonical import pct
from .robot.robot_api import TaskState

# Task states that mean a mission is under way
MISSION_TASK_STATES = (TaskState.RUNNING.value, TaskState.PAUSED.value, TaskState.OTHER.value)

# Level fields report -1 when the model does not support them
LEVEL_UNAVAILABLE = -1


def build_key_values(
    status: dict[str, Any],
    status_v2: dict[str, Any],
    robot_data: dict[str, Any],
    api_connected: bool,
    connector_version: str,
) -> dict[str, Any]:
    """Canonical key-values for one execution loop tick. Keys without a value are omitted."""
    battery = status.get("battery", {})
    localization = status.get("localizationInfo", {})
    device = status.get("device", {})
    device_v2 = status_v2.get("device", {})
    current_task = status_v2.get("currentTask", {})

    key_values = {
        "api_connected": api_connected,
        "connector_version": connector_version,
        "display_name": robot_data.get("displayName", ""),
        "model_family": robot_data.get("modelFamilyCode", ""),
        "model_type": robot_data.get("modelTypeCode", ""),
        "software_version": robot_data.get("softwareVersion", ""),
        "battery_pct": pct(battery.get("powerPercentage")),
        "charging": battery.get("charging"),
        "battery_soh": battery.get("soh"),
        "battery_cycles": battery.get("cycleTimes"),
        "battery_temp_c": _max_battery_temperature(battery),
        "robot_online": status.get("online"),
        "emergency_stop": status.get("emergencyStop", {}).get("enabled"),
        "speed_kmph": status.get("speedKilometerPerHour"),
        "current_map_name": localization.get("map", {}).get("name"),
        "localization_state": localization.get("localizationState"),
        "nav_status": status.get("navStatus"),
        "elevator_status": status.get("currentElevatorStatus"),
        "manual_control": current_task.get("manualControlling"),
        "clean_water_tank_pct": pct(device.get("cleanWaterTank", {}).get("level")),
        "recovery_tank_pct": pct(device.get("recoveryWaterTank", {}).get("level")),
        "spray_active": device.get("spray", {}).get("isRunning"),
        "spray_water_level": _available(device.get("spray", {}).get("waterLevel")),
        "vacuum_active": device.get("vacuum", {}).get("enabled"),
        "vacuum_level": _available(device_v2.get("vacuum", {}).get("level")),
        "filter_active": device.get("filter", {}).get("isRunning"),
        "scrubber_brush_active": device.get("scrubberBrush", {}).get("enabled"),
        "scrubber_brush_down": device.get("scrubberBrush", {}).get("ifPutDown"),
        "soft_squeegee_down": device.get("softSqueegee", {}).get("ifPutDown"),
        "rolling_squeegee_down": device.get("rollingSqueegee", {}).get("ifPutDown"),
        "side_brush_left_down": device.get("leftSideBrush", {}).get("ifPutDown"),
        "side_brush_right_down": device.get("rightSideBrush", {}).get("ifPutDown"),
        "executable_tasks": _executable_tasks(status),
        "nav_points": _nav_points(status_v2),
        "work_modes": status.get("workModes") or status_v2.get("workModes"),
        "mission_status": _mission_status(status, status_v2),
        **_task_state(status),
        **cleaning_mode_keys(current_task.get("workMode", {}).get("name")),
        # v1 is the primary status, v2 adds the parts only it reports on some S models
        **_consumable_wear({**device_v2, **device}),
    }
    return {key: value for key, value in key_values.items() if value is not None}


def _available(level: Any) -> Any:
    return None if level == LEVEL_UNAVAILABLE else level


def _max_battery_temperature(battery: dict[str, Any]) -> float | None:
    """Hottest of the per-cell temperatures, which is the alert relevant figure."""
    temperatures = [
        value
        for key, value in battery.items()
        if key.startswith("temperature") and isinstance(value, (int, float))
    ]
    return max(temperatures) if temperatures else None


def _executable_tasks(status: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": task.get("id"),
            "name": task.get("name"),
            "map_name": task.get("map", {}).get("name"),
        }
        for task in status.get("executableTasks", [])
    ]


def _nav_points(status_v2: dict[str, Any]) -> list[str]:
    points = status_v2.get("navigationPoints", {}).get("naviPoints", [])
    return [point.get("naviPointName") for point in points if point.get("naviPointName")]


def _task_state(status: dict[str, Any]) -> dict[str, str]:
    task_state = status.get("taskState")
    if not task_state:
        return {}
    return {"task_state": normalize_task_state(task_state), "task_state_raw": task_state}


def _consumable_wear(device: dict[str, Any]) -> dict[str, float]:
    """Consumed fraction of every device part reporting a life span.

    The part set varies by model, so it is derived instead of hardcoded.
    e.g. {"softSqueegee": {"lifeSpan": 250, "usedLife": 25}} ->
    {"consumable_soft_squeegee_wear_pct": 0.1}
    """
    wear = {}
    for part, values in device.items():
        if not isinstance(values, dict):
            continue
        life_span = values.get("lifeSpan")
        used_life = values.get("usedLife")
        if not life_span or not isinstance(used_life, (int, float)):
            continue
        wear[f"consumable_{camel_to_snake(part)}_wear_pct"] = min(
            1.0, max(0.0, used_life / life_span)
        )
    return wear


def _mission_status(status: dict[str, Any], status_v2: dict[str, Any]) -> str | None:
    """Robot mode value, homogeneous across cleaning connectors so a single Modes configuration
    serves every OEM. Omitted while the vendor state is unknown, so the cloud keeps the last
    known mode instead of being told the robot is idle.
    """
    task_state = status.get("taskState")
    if not task_state:
        return None
    if status.get("emergencyStop", {}).get("enabled"):
        return "Error"
    if task_state in MISSION_TASK_STATES or status_v2.get("currentTask", {}).get("taskInstanceId"):
        return "Mission"
    if status.get("battery", {}).get("charging"):
        return "Charging"
    return "Idle"
