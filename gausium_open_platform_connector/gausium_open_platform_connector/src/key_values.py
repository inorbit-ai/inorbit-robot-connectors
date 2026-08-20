# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Canonical cleaning-vertical key-values built from the Gausium status payloads."""

# Standard
import re
from typing import Any

# Local
from gausium_open_platform_connector.src.mission import (
    TaskState,
    normalize_cleaning_mode,
    normalize_task_state,
)

_CAMEL_RE = re.compile(r"(?<!^)(?=[A-Z])")

_TEMPERATURE_RE = re.compile(r"temperature\d+$")


def _snake(name: str) -> str:
    return _CAMEL_RE.sub("_", name).lower()


def _pct(value: float | None) -> float | None:
    return value / 100 if value is not None else None


def _level(value: float | None) -> float | None:
    # -1 means not available
    return None if value == -1 else value


def _consumable_wear(device: dict[str, Any]) -> dict[str, float]:
    """Wear ratio for every device part carrying a life span, clamped to 0-1.

    No hardcoded part list: the set of consumables varies by robot model. The vendor
    units are undocumented but the ratio is unit-free.
    """
    wear = {}
    for part, info in device.items():
        if not isinstance(info, dict):
            continue
        life_span, used_life = info.get("lifeSpan"), info.get("usedLife")
        if not life_span or life_span < 0 or used_life is None:
            continue
        wear[f"consumable_{_snake(part)}_wear_pct"] = min(max(used_life / life_span, 0.0), 1.0)
    return wear


def derive_mission_status(status: dict[str, Any], status_v2: dict[str, Any]) -> str | None:
    """Derive the ``mission_status`` mode value, homogeneous across cleaning connectors.

    First match wins; Mission outranks Charging per the contract. Returns ``None``
    (key omitted) when the task state is absent, so the cloud retains the last known
    mode instead of being told the robot is idle.
    """
    task_state = status.get("taskState")
    if task_state is None:
        return None
    if status.get("emergencyStop", {}).get("enabled"):
        return "Error"
    if task_state in (TaskState.RUNNING, TaskState.PAUSED, TaskState.OTHER) or status_v2.get(
        "currentTask", {}
    ).get("taskInstanceId"):
        return "Mission"
    if status.get("battery", {}).get("charging"):
        return "Charging"
    if task_state == TaskState.IDLE:
        return "Idle"
    return None


def _executable_tasks(status: dict[str, Any]) -> list[dict] | None:
    tasks = status.get("executableTasks")
    if tasks is None:
        return None
    return [
        {
            "id": task.get("id"),
            "name": task.get("name"),
            "map_name": task.get("map", {}).get("name"),
        }
        for task in tasks
    ]


def _nav_points(status_v2: dict[str, Any]) -> list[str] | None:
    points = status_v2.get("navigationPoints", {}).get("naviPoints")
    if points is None:
        return None
    return [point.get("naviPointName") for point in points]


def _work_modes(status: dict[str, Any], status_v2: dict[str, Any]) -> list[dict] | None:
    modes = status.get("workModes") or status_v2.get("workModes")
    if modes is None:
        return None
    return [
        {
            "id": mode.get("id"),
            "name": mode.get("name"),
            "strength": mode.get("strength"),
            "type": mode.get("type"),
        }
        for mode in modes
    ]


def build_key_values(status: dict[str, Any], status_v2: dict[str, Any]) -> dict[str, Any]:
    """Build the canonical key-values from the v1 and v2 status payloads.

    Percentages are published as 0-1. Missing vendor fields are omitted rather than
    published as null.
    """
    battery = status.get("battery", {})
    device = status.get("device", {})
    localization = status.get("localizationInfo", {})
    current_task = status_v2.get("currentTask", {})

    temperatures = [value for key, value in battery.items() if _TEMPERATURE_RE.fullmatch(key)]

    key_values = {
        "battery_pct": _pct(battery.get("powerPercentage")),
        "charging": battery.get("charging"),
        "task_state": normalize_task_state(status.get("taskState")),
        "task_state_raw": status.get("taskState"),
        "robot_online": status.get("online"),
        "current_map_name": localization.get("map", {}).get("name"),
        "clean_water_tank_pct": _pct(device.get("cleanWaterTank", {}).get("level")),
        "recovery_tank_pct": _pct(device.get("recoveryWaterTank", {}).get("level")),
        "emergency_stop": status.get("emergencyStop", {}).get("enabled"),
        "speed_kmph": status.get("speedKilometerPerHour"),
        "mission_status": derive_mission_status(status, status_v2),
        "localization_state": localization.get("localizationState"),
        "nav_status": status.get("navStatus"),
        "elevator_status": status.get("currentElevatorStatus"),
        "manual_control": current_task.get("manualControlling"),
        "battery_soh": battery.get("soh"),
        "battery_cycles": battery.get("cycleTimes"),
        "battery_temp_c": max(temperatures) if temperatures else None,
        "spray_active": device.get("spray", {}).get("isRunning"),
        "spray_water_level": _level(device.get("spray", {}).get("waterLevel")),
        "vacuum_active": device.get("vacuum", {}).get("enabled"),
        "vacuum_level": _level(status_v2.get("device", {}).get("vacuum", {}).get("level")),
        "filter_active": device.get("filter", {}).get("isRunning"),
        "scrubber_brush_active": device.get("scrubberBrush", {}).get("enabled"),
        "scrubber_brush_down": device.get("scrubberBrush", {}).get("ifPutDown"),
        "soft_squeegee_down": device.get("softSqueegee", {}).get("ifPutDown"),
        "rolling_squeegee_down": device.get("rollingSqueegee", {}).get("ifPutDown"),
        "side_brush_left_down": device.get("leftSideBrush", {}).get("ifPutDown"),
        "side_brush_right_down": device.get("rightSideBrush", {}).get("ifPutDown"),
        "executable_tasks": _executable_tasks(status),
        "nav_points": _nav_points(status_v2),
        "work_modes": _work_modes(status, status_v2),
        # v2 exposes consumables the v1 payload lacks on some models
        **_consumable_wear({**device, **status_v2.get("device", {})}),
    }
    cleaning_mode = current_task.get("workMode", {}).get("name")
    if cleaning_mode:
        key_values["cleaning_mode"] = normalize_cleaning_mode(cleaning_mode)
        key_values["cleaning_mode_raw"] = cleaning_mode
    return {key: value for key, value in key_values.items() if value is not None}
