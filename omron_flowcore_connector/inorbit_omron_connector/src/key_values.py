# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Key-value builders for the FlowCore connector.

Health key-values describe the connector's own view and are published every
tick. Telemetry key-values restate robot data and are published only when
FlowCore refreshed them.
"""

from typing import Any, Optional

BUSY_SUB_STATUSES = frozenset(
    {"Driving", "BeforePickup", "AfterDropoff", "BeforeDropoff", "BeforeEvery", "AfterEvery"}
)
CHARGING_SUB_STATUSES = frozenset(
    {"Docked", "Docking", "Charging", "DockParking", "DockParked", "ForcedDocking"}
)
IDLE_SUB_STATUSES = frozenset({"Available", "Parked", "Allocated", "Unallocated"})
ERROR_SUB_STATUSES = frozenset(
    {"EStopPressed", "Fault", "MotorsDisabled", "Lost", "NotLocalized"}
)


def map_status(sub_status: str) -> str:
    """Map an AMR sub-status to an InOrbit robot status."""
    if sub_status in BUSY_SUB_STATUSES:
        return "BUSY"
    if sub_status in CHARGING_SUB_STATUSES:
        return "CHARGING"
    if sub_status in ERROR_SUB_STATUSES:
        return "ERROR"
    return "IDLE"


def build_health_key_values(
    api_connected: bool, robot_attached: bool, connector_version: str
) -> dict[str, Any]:
    """Connector-view key-values, published every tick even while nothing is reachable.

    ``robot_attached`` is only knowable while the API is reachable, so it is omitted
    otherwise and the datasource keeps its last known value instead of restating a
    stale one.
    """
    key_values: dict[str, Any] = {
        "connector_version": connector_version,
        "api_connected": api_connected,
    }
    if api_connected:
        key_values["robot_attached"] = robot_attached
    return key_values


def build_key_values(summary: Optional[Any], battery: Optional[Any]) -> dict[str, Any]:
    """Robot telemetry key-values from the cached fleet summary and battery value."""
    key_values: dict[str, Any] = {}
    if battery is not None:
        key_values["battery_percent"] = float(battery.value)
    if summary is not None:
        key_values["omron_status"] = summary.status
        key_values["omron_sub_status"] = summary.subStatus
        key_values["status"] = map_status(summary.subStatus)
        if summary.ipAddress:
            key_values["robot_ip"] = summary.ipAddress
    return key_values
