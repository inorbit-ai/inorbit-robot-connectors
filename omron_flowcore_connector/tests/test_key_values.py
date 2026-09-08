# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Tests for the key-value builders."""

import pytest

from inorbit_omron_connector.src.key_values import (
    build_health_key_values,
    build_robot_key_values,
    build_vendor_key_values,
    map_status,
)
from inorbit_omron_connector.src.omron.models import (
    DataStoreResponse,
    OmronUpdate,
    RobotResponse,
)


def _summary(status="Available", sub_status="Unallocated", ip="10.0.0.1"):
    return RobotResponse(
        namekey="Robot1",
        upd=OmronUpdate(millis=1),
        status=status,
        subStatus=sub_status,
        ipAddress=ip,
    )


def _battery(value=50.0):
    return DataStoreResponse(
        namekey="StateOfCharge:Robot1", upd=OmronUpdate(millis=1), value=value
    )


def test_health_key_values_report_the_connector_view():
    result = build_health_key_values(
        api_connected=True, robot_attached=True, connector_version="1.2.3"
    )

    assert result == {
        "connector_version": "1.2.3",
        "api_connected": True,
        "robot_attached": True,
    }


def test_health_key_values_omit_attachment_when_the_api_is_down():
    result = build_health_key_values(
        api_connected=False, robot_attached=False, connector_version="1.2.3"
    )

    assert result == {"connector_version": "1.2.3", "api_connected": False}


def test_vendor_key_values_carry_the_fleet_summary():
    result = build_vendor_key_values(_summary())

    assert result == {
        "omron_status": "Available",
        "omron_sub_status": "Unallocated",
        "status": "IDLE",
        "robot_ip": "10.0.0.1",
    }


def test_vendor_key_values_omit_robot_ip_when_unset():
    result = build_vendor_key_values(_summary(ip=None))

    assert result == {
        "omron_status": "Available",
        "omron_sub_status": "Unallocated",
        "status": "IDLE",
    }


def test_vendor_key_values_are_empty_without_data():
    assert build_vendor_key_values(None) == {}


def test_robot_key_values_carry_battery():
    result = build_robot_key_values(_battery())

    assert result == {"battery_percent": 50.0}


def test_robot_key_values_are_empty_without_data():
    assert build_robot_key_values(None) == {}


def test_map_status_maps_the_documented_sub_statuses():
    assert map_status("Driving") == "BUSY"
    assert map_status("Docked") == "CHARGING"
    assert map_status("Available") == "IDLE"
    assert map_status("SomethingNew") == "IDLE"


@pytest.mark.parametrize(
    "sub_status",
    [
        "EstopPressed",
        "Fault",
        "MotorsDisabled",
        "Lost",
        "Disconnected",
        "OutgoingArclConnectionLost",
    ],
)
def test_map_status_maps_every_error_sub_status(sub_status):
    assert map_status(sub_status) == "ERROR"



def test_map_status_warns_on_an_unrecognised_sub_status(caplog):
    with caplog.at_level("WARNING"):
        result = map_status("SomethingNew")

    assert result == "IDLE"
    assert "SomethingNew" in caplog.text


def test_map_status_known_idle_sub_status_does_not_warn(caplog):
    with caplog.at_level("WARNING"):
        result = map_status("Unallocated")

    assert result == "IDLE"
    assert caplog.text == ""
