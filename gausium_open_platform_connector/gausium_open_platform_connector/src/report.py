# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Canonical mission data extracted from a Gausium task report.

Transport agnostic: the polled v2 API sends ISO 8601 timestamps and the report push callback
sends epoch milliseconds, and both are accepted.
"""

# Standard
from typing import Any

# Local
from gausium_open_platform_connector.src.canonical import (
    cleaning_mode_keys,
    pct,
    report_time_to_millis,
    slug,
)


def report_to_data(
    report: dict[str, Any],
    current_map_name: str | None = None,
    interruptions_count: int | None = None,
) -> dict[str, Any]:
    """Canonical mission data for a completed task report. Keys without a value are omitted."""
    planned_area = report.get("plannedCleaningAreaSquareMeter")
    cleaned_area = report.get("actualCleaningAreaSquareMeter")
    active_time_s = _whole_seconds(report.get("durationSeconds"))
    start_ms = report_time_to_millis(report.get("startTime"))
    end_ms = report_time_to_millis(report.get("endTime"))
    start_battery = report.get("startBatteryPercentage")
    end_battery = report.get("endBatteryPercentage")
    residual = report.get("consumablesResidualPercentage", {})
    sub_tasks = report.get("subTasks") or []
    map_names = list(dict.fromkeys(s["mapName"] for s in sub_tasks if s.get("mapName")))

    data = {
        "report_id": report.get("id"),
        "task_id": report.get("taskId"),
        "plan_id": report.get("planId"),
        "task_instance_id": report.get("taskInstanceId"),
        "planned_area_m2": planned_area,
        "cleaned_area_m2": cleaned_area,
        "coverage_pct": _coverage_pct(cleaned_area, planned_area, report),
        "duration_s": round((end_ms - start_ms) / 1000) if start_ms and end_ms else None,
        "active_cleaning_time_s": active_time_s,
        "efficiency_m2ph": _efficiency_m2ph(cleaned_area, active_time_s, report),
        "water_used_l": report.get("waterConsumptionLiter"),
        "battery_start_pct": pct(start_battery),
        "battery_end_pct": pct(end_battery),
        "battery_used_pct": _battery_used_pct(start_battery, end_battery),
        "polished_area_planned_m2": report.get("plannedPolishingAreaSquareMeter"),
        "polished_area_m2": report.get("actualPolishingAreaSquareMeter"),
        "operator": report.get("operator"),
        "area_names": report.get("areaNameList"),
        "loop_count": report.get("loopCount"),
        "expected_loop_count": report.get("expectedLoopCount"),
        "task_progress": report.get("taskProgress"),
        "task_end_status_raw": report.get("taskEndStatus"),
        "report_image_url": report.get("taskReportPngUri"),
        "map_name": ", ".join(map_names) or current_map_name,
        "floors_cleaned_count": len(sub_tasks),
        "interruptions_count": interruptions_count,
        "consumable_brush_pct": pct(residual.get("brush")),
        "consumable_filter_pct": pct(residual.get("filter")),
        "consumable_suction_blade_pct": pct(residual.get("suctionBlade")),
        **cleaning_mode_keys(report.get("cleaningMode")),
        **_per_map_areas(sub_tasks),
    }
    return {key: value for key, value in data.items() if value is not None}


def _whole_seconds(value: Any) -> int | None:
    return round(value) if isinstance(value, (int, float)) else None


def _coverage_pct(cleaned_area: Any, planned_area: Any, report: dict[str, Any]) -> float | None:
    """Cleaned over planned, the definition shared across cleaning connectors. The vendor's own
    completion percentage is the fallback when either area is missing.
    """
    if isinstance(cleaned_area, (int, float)) and planned_area:
        return round(min(1.0, max(0.0, cleaned_area / planned_area)), 4)
    return report.get("completionPercentage")


def _efficiency_m2ph(cleaned_area: Any, active_time_s: int | None, report: dict) -> float | None:
    """Computed rather than taken from the vendor, whose figure uses an undocumented time base."""
    if isinstance(cleaned_area, (int, float)) and active_time_s:
        return round(cleaned_area / (active_time_s / 3600), 1)
    return report.get("efficiencySquareMeterPerHour")


def _battery_used_pct(start_battery: Any, end_battery: Any) -> float | None:
    """Withheld when a mid-task recharge would make the subtraction negative."""
    if not isinstance(start_battery, (int, float)) or not isinstance(end_battery, (int, float)):
        return None
    return pct(start_battery - end_battery) if start_battery >= end_battery else None


def _per_map_areas(sub_tasks: list[dict[str, Any]]) -> dict[str, float]:
    """Cleaned area per map covered by the task. A sub-task is a map or floor, not a zone.

    e.g. [{"mapName": "Floor 1", "actualCleaningAreaSquareMeter": 10.0}] ->
    {"map_floor_1_cleaned_area_m2": 10.0}
    """
    areas: dict[str, float] = {}
    for sub_task in sub_tasks:
        name = sub_task.get("mapName")
        area = sub_task.get("actualCleaningAreaSquareMeter")
        if not name or not isinstance(area, (int, float)):
            continue
        key, collisions = f"map_{slug(name)}_cleaned_area_m2", 1
        while key in areas:
            collisions += 1
            key = f"map_{slug(name)}_{collisions}_cleaned_area_m2"
        areas[key] = area
    return areas
