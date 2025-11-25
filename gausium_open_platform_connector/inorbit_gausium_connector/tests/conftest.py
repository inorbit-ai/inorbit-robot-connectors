# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest

# Fixtures defined in conftest.py do not require importing


@pytest.fixture(autouse=True)
def disable_network_calls(httpx_mock):
    # Including httpx_mock will disable network calls on every test that uses httpx
    # Tests that need specific HTTP responses should configure httpx_mock explicitly
    pass


@pytest.fixture
def sample_status_data():
    # Sample return value from robot_api.get_status()
    return {
        "battery_percentage": 93.5,
        "battery_time_remaining": 89725,
        "uptime": 123456,
        "robot_name": "Wall-E",
        "robot_model": "hoolibot3000",
        "cpu": 12.5,
        "memory_usage": 33.3,
        "errors": [],
        "distance_to_next_target": 120,
        "velocity": {"linear": 1.1, "angular": 180},
        "position": {
            "y": 7.156267166137695,
            "x": 9.52050495147705,
            "orientation": 104.30510711669922,
        },
    }
