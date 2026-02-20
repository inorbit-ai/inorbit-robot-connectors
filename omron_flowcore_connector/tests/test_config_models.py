# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Tests for `inorbit_omron_connector.src.config.models`."""

from __future__ import annotations

import copy
from pathlib import Path
import pytest
from inorbit_omron_connector.src.config.models import (
    FlowCoreConfig,
    FlowCoreConnectorConfig,
    FlowCoreRobotConfig,
)

REQUIRED_CONNECTOR_CONFIG = {
    "url": "https://flowcore.example.com",
    "password": "test-pass",
    "arcl_password": "arcl-pass",
}

@pytest.fixture()
def base_config_data() -> dict:
    """Return a minimal, valid FlowCoreConnectorConfig payload."""
    return {
        "connector_type": "flowcore",
        "connector_config": {
            "url": "https://flowcore.example.com",
            "password": "dummy-pass",
            "arcl_password": "arcl-pass",
        },
        "fleet": [
            {"robot_id": "robot-alpha", "fleet_robot_id": "NameKey1", "cameras": []},
            {"robot_id": "robot-beta", "fleet_robot_id": "NameKey2", "cameras": []},
        ],
    }

def test_connector_type_must_match(base_config_data: dict) -> None:
    config = FlowCoreConnectorConfig(**base_config_data)
    assert config.connector_type == "flowcore"

def test_invalid_connector_type_raises(base_config_data: dict) -> None:
    data = copy.deepcopy(base_config_data)
    data["connector_type"] = "not-flowcore"

    with pytest.raises(ValueError, match="Expected connector type 'flowcore'"):
        FlowCoreConnectorConfig(**data)

def test_unique_fleet_robot_ids_are_required(base_config_data: dict) -> None:
    data = copy.deepcopy(base_config_data)
    # Duplicate fleet_robot_id
    data["fleet"][1]["fleet_robot_id"] = data["fleet"][0]["fleet_robot_id"]

    with pytest.raises(ValueError, match="fleet_robot_id values must be unique"):
        FlowCoreConnectorConfig(**data)

def test_valid_config_instantiates_models(base_config_data: dict) -> None:
    config = FlowCoreConnectorConfig(**base_config_data)

    assert isinstance(config.connector_config, FlowCoreConfig)
    assert all(isinstance(robot, FlowCoreRobotConfig) for robot in config.fleet)

def test_flowcore_config_reads_from_environment_variables(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Test that FlowCoreConfig reads missing fields from environment variables."""
    monkeypatch.setenv("INORBIT_FLOWCORE_URL", "https://env.example.com")
    monkeypatch.setenv("INORBIT_FLOWCORE_PASSWORD", "env-pass")
    monkeypatch.setenv("INORBIT_FLOWCORE_ARCL_PASSWORD", "arcl-env-pass")
    monkeypatch.setenv("INORBIT_FLOWCORE_VERIFY_SSL", "true")
    monkeypatch.setenv("INORBIT_FLOWCORE_ARCL_TIMEOUT", "15")

    # Pass only required fields that are NOT in env (none in this test case, 
    # but BaseSettings needs nothing if env is full, except we might want to check partials)
    
    # Init empty or partial to trigger env load. 
    # Since 'password' and 'url' are required, if they are in env, we can omit them in constructor.
    # BaseSettings behavior: constructor args > env vars > defaults.
    # If we want to test env loading, we don't pass them in constructor.

    config = FlowCoreConfig()

    assert config.url == "https://env.example.com"
    assert config.password == "env-pass"
    assert config.arcl_password == "arcl-env-pass"
    assert config.arcl_timeout == 15
    assert config.verify_ssl is True
    assert config.username == "toolkitadmin" # Default

def test_flowcore_config_prioritizes_yaml_args_over_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that explicit args take precedence over environment variables."""
    monkeypatch.setenv("INORBIT_FLOWCORE_URL", "https://env.example.com")
    monkeypatch.setenv("INORBIT_FLOWCORE_PASSWORD", "env-pass")
    monkeypatch.setenv("INORBIT_FLOWCORE_ARCL_PASSWORD", "arcl-env-pass")

    config = FlowCoreConfig(
        url="https://arg.example.com",
        password="arg-pass",
        arcl_password="arg-arcl-pass",
        arcl_timeout=10,
    )

    assert config.url == "https://arg.example.com"
    assert config.password == "arg-pass"
    assert config.arcl_password == "arg-arcl-pass"
    assert config.arcl_timeout == 10


def test_flowcore_config_defaults() -> None:
    config = FlowCoreConfig(**REQUIRED_CONNECTOR_CONFIG)
    assert config.verify_ssl is False
