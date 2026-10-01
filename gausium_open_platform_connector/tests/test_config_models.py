# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Tests for `gausium_open_platform_connector.src.config.models`."""

from __future__ import annotations

import copy

import pytest

from gausium_open_platform_connector.src.config.models import (
    CONNECTOR_TYPE,
    DEFAULT_BASE_URL,
    GausiumOpenPlatformConfig,
    GausiumOpenPlatformConnectorConfig,
    GausiumOpenPlatformRobotConfig,
)

CREDENTIALS = {
    "client_id": "test-client-id",
    "client_secret": "test-client-secret",
    "access_key_secret": "test-access-key",
}


@pytest.fixture()
def base_config_data() -> dict:
    """Return a minimal, valid GausiumOpenPlatformConnectorConfig payload."""

    return {
        "api_key": "test-api-key",
        "connector_type": "gausium_open_platform",
        "connector_config": dict(CREDENTIALS),
        "fleet": [
            {"robot_id": "robot-alpha", "serial_number": "GS000-0000-000-0001", "cameras": []},
            {"robot_id": "robot-beta", "serial_number": "GS000-0000-000-0002", "cameras": []},
        ],
    }


def test_connector_type_must_match(base_config_data: dict) -> None:
    config = GausiumOpenPlatformConnectorConfig(**base_config_data, _env_file=None)
    assert config.connector_type == CONNECTOR_TYPE


def test_invalid_connector_type_raises(base_config_data: dict) -> None:
    data = copy.deepcopy(base_config_data)
    data["connector_type"] = f"not-{CONNECTOR_TYPE}"

    with pytest.raises(
        ValueError,
        match=rf"does not match CONNECTOR_TYPE '{CONNECTOR_TYPE}'",
    ):
        GausiumOpenPlatformConnectorConfig(**data, _env_file=None)


def test_unique_serial_numbers_are_required(base_config_data: dict) -> None:
    data = copy.deepcopy(base_config_data)
    data["fleet"][1]["serial_number"] = data["fleet"][0]["serial_number"]

    with pytest.raises(ValueError, match="serial_number values must be unique"):
        GausiumOpenPlatformConnectorConfig(**data, _env_file=None)


def test_valid_config_instantiates_models(base_config_data: dict) -> None:
    config = GausiumOpenPlatformConnectorConfig(**base_config_data, _env_file=None)

    assert isinstance(config.connector_config, GausiumOpenPlatformConfig)
    assert all(isinstance(robot, GausiumOpenPlatformRobotConfig) for robot in config.fleet)


def test_config_defaults() -> None:
    config = GausiumOpenPlatformConfig(**CREDENTIALS, _env_file=None)

    assert str(config.base_url) == DEFAULT_BASE_URL
    assert config.api_timeout == 10.0
    assert config.mission_success_percentage_threshold == 0.90


def test_config_reads_from_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing fields are read from INORBIT_GAUSIUM_OPEN_PLATFORM_* environment variables."""
    monkeypatch.setenv("INORBIT_GAUSIUM_OPEN_PLATFORM_CLIENT_ID", "env-client-id")
    monkeypatch.setenv("INORBIT_GAUSIUM_OPEN_PLATFORM_CLIENT_SECRET", "env-client-secret")
    monkeypatch.setenv("INORBIT_GAUSIUM_OPEN_PLATFORM_ACCESS_KEY_SECRET", "env-access-key")

    config = GausiumOpenPlatformConfig(_env_file=None)

    assert config.client_id == "env-client-id"
    assert config.client_secret == "env-client-secret"
    assert config.access_key_secret == "env-access-key"


def test_config_prioritizes_yaml_over_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """YAML values take precedence over environment variables."""
    monkeypatch.setenv("INORBIT_GAUSIUM_OPEN_PLATFORM_CLIENT_ID", "env-client-id")

    config = GausiumOpenPlatformConfig(**CREDENTIALS, _env_file=None)

    assert config.client_id == "test-client-id"


def test_mission_success_percentage_threshold_bounds() -> None:
    with pytest.raises(ValueError):
        GausiumOpenPlatformConfig(
            **CREDENTIALS, mission_success_percentage_threshold=1.5, _env_file=None
        )
