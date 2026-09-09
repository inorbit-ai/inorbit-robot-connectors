# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Key-value builders for the FlowCore connector.

Health key-values describe the connector's own view and are published every
tick. Vendor key-values come from `/Robot/UpdatedSince`, FlowCore's own
statement about the robot, and keep arriving correctly even while the robot
itself is unreachable. Robot key-values come from `/DataStoreValueLatest`,
the robot's own telemetry, which keeps flowing for as long as the robot is
reporting, whether or not the Fleet Manager can still command it.
"""

from typing import Any, Optional

from .omron.models import DataStoreResponse, RobotResponse

BUSY_SUB_STATUSES = frozenset(
    {"Driving", "BeforePickup", "AfterDropoff", "BeforeDropoff", "BeforeEvery", "AfterEvery"}
)
CHARGING_SUB_STATUSES = frozenset(
    {"Docked", "Docking", "Charging", "DockParking", "DockParked", "ForcedDocking"}
)
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


def build_vendor_key_values(summary: Optional[RobotResponse]) -> dict[str, Any]:
    """FlowCore's own statement about a robot, from `/Robot/UpdatedSince`.

    This is the fleet summary, not the robot's own telemetry: it keeps arriving
    correctly even while the robot itself is unreachable, so it publishes whenever
    the API is connected, regardless of whether the robot is online.
    """
    if summary is None:
        return {}
    key_values: dict[str, Any] = {
        "omron_status": summary.status,
        "omron_sub_status": summary.subStatus,
        "status": map_status(summary.subStatus),
    }
    if summary.ipAddress:
        key_values["robot_ip"] = summary.ipAddress
    return key_values


def build_robot_key_values(battery: Optional[DataStoreResponse]) -> dict[str, Any]:
    """The robot's own telemetry, from `/DataStoreValueLatest`.

    Published when the value changes, with no online check on top: a robot whose
    ARCL link the Fleet Manager has lost keeps reporting here, and a robot that has
    truly dropped reports nothing at all, so the cached value holds by itself.
    """
    if battery is None:
        return {}
    return {"battery_percent": float(battery.value)}
