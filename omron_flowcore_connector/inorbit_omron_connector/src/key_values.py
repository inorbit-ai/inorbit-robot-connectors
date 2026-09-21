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

import logging
from typing import Any, Optional

from .omron.arcl_client import BLOCK_DRIVING_FAULT
from .omron.models import DataStoreResponse, RobotResponse

LOGGER = logging.getLogger(__name__)

BUSY_SUB_STATUSES = frozenset(
    {"Driving", "BeforePickup", "AfterDropoff", "BeforeDropoff", "BeforeEvery", "AfterEvery"}
)
# Only consulted when the robot does not report `RobotChargeStateNumber`: being on a
# dock is not the same as drawing charge (FlowCore reports `DockingState: Docking` with
# `ChargeState: Not`), and a contactless pad charges a robot that never docks at all.
CHARGING_SUB_STATUSES = frozenset(
    {"Docked", "Docking", "Charging", "DockParking", "DockParked", "ForcedDocking"}
)
# `Disconnected` is undocumented: found by probing a live Fleet Manager, not in
# the manual. Without it, a dropped robot maps to IDLE and looks available.
# `OutgoingArclConnectionLost` is the Fleet Manager's own command channel being
# down, not the robot being unreachable, so the robot stays online; ERROR is how
# an operator learns FlowCore cannot dispatch to it.
ERROR_SUB_STATUSES = frozenset(
    {
        "EstopPressed",
        "Fault",
        "MotorsDisabled",
        "Lost",
        "Disconnected",
        "OutgoingArclConnectionLost",
    }
)
IDLE_SUB_STATUSES = frozenset({"Available", "Parked", "Allocated", "Unallocated"})


def map_status(
    sub_status: str, charging: Optional[bool] = None, faults: tuple[str, ...] = ()
) -> str:
    """Map an AMR sub-status and its active faults to an InOrbit robot status.

    `charging` is the robot's own charge report, or None when it does not publish one.
    Work and faults outrank it: an e-stopped robot on a charger is in ERROR, which is
    what an operator has to act on.

    `faults` are the robot's active faults by name. Our own hold alone is PAUSED, any
    other fault is ERROR.
    """
    if faults:
        return "PAUSED" if set(faults) == {BLOCK_DRIVING_FAULT} else "ERROR"
    if sub_status in BUSY_SUB_STATUSES:
        return "BUSY"
    if sub_status in ERROR_SUB_STATUSES:
        return "ERROR"
    if charging:
        return "CHARGING"
    if charging is None and sub_status in CHARGING_SUB_STATUSES:
        return "CHARGING"
    if sub_status in CHARGING_SUB_STATUSES or sub_status in IDLE_SUB_STATUSES:
        return "IDLE"
    # Reached only by a documented-but-unclassified value (e.g. AvailableForJobs,
    # Parking, Interrupted) or a genuinely unknown one. Either way this connector
    # has no classification for it: the warning is a prompt to classify it, not
    # noise to silence.
    LOGGER.warning("Unrecognised sub-status %r, publishing as IDLE.", sub_status)
    return "IDLE"


def build_health_key_values(
    api_connected: bool,
    robot_attached: bool,
    connector_version: str,
    offline_reason: Optional[str],
) -> dict[str, Any]:
    """Connector-view key-values, published every tick even while nothing is reachable.

    ``robot_online`` is the connector's own verdict, which is what tells an operator
    that InOrbit showing a robot offline is this connector's decision rather than a
    dropped session. ``offline_reason`` names which condition made that decision; it
    publishes as an empty string while the robot is online, rather than being omitted,
    so a recovered robot does not keep displaying the reason it went down.

    ``robot_attached`` is only knowable while the API is reachable, so it is omitted
    otherwise and the datasource keeps its last known value instead of restating a
    stale one.
    """
    key_values: dict[str, Any] = {
        "connector_version": connector_version,
        "api_connected": api_connected,
        "robot_online": offline_reason is None,
        "offline_reason": offline_reason or "",
    }
    if api_connected:
        key_values["robot_attached"] = robot_attached
    return key_values


def build_vendor_key_values(
    summary: Optional[RobotResponse],
    charging: Optional[bool] = None,
    faults: tuple[str, ...] = (),
) -> dict[str, Any]:
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
        "status": map_status(summary.subStatus, charging, faults),
        "omron_active_faults": ", ".join(faults),
    }
    if summary.ipAddress:
        key_values["robot_ip"] = summary.ipAddress
    return key_values


def build_robot_key_values(
    battery: Optional[DataStoreResponse],
    charge_state: Optional[DataStoreResponse] = None,
    docking_state: Optional[DataStoreResponse] = None,
) -> dict[str, Any]:
    """The robot's own telemetry, from `/DataStoreValueLatest`.

    Published every tick for as long as the robot is reporting, with no online check
    on top: a robot whose ARCL link the Fleet Manager has lost keeps reporting here,
    and the value being unchanged says the robot is idle, not that it is stale.

    Each item is published on its own: a robot that reports battery but no charge state
    still publishes its battery. `omron_charge_state` is passed through verbatim
    (`Not`, `Bulk`, `Overcharge`, `Float`) rather than derived, so a stage this connector
    does not know about still reaches the operator.
    """
    key_values: dict[str, Any] = {}
    if battery is not None:
        key_values["battery_percent"] = float(battery.value)
    if charge_state is not None and charge_state.value is not None:
        key_values["omron_charge_state"] = str(charge_state.value)
    if docking_state is not None and docking_state.value is not None:
        key_values["omron_docking_state"] = str(docking_state.value)
    return key_values
