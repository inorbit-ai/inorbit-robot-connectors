# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from inorbit_gausium_connector.src.config.connector_model import ConnectorConfig
from inorbit_gausium_connector.src.config.connector_model import default_config
from inorbit_gausium_connector.src.config.connector_model import GausiumConnectorConfig
from inorbit_gausium_connector.src.robot.robot_factory import ROBOT_API_CLASSES
from pydantic import HttpUrl
from pydantic import ValidationError


@pytest.fixture
def example_configuration_dict():
    return {
        "inorbit_robot_key": "1234567890",
        "location_tz": "America/Los_Angeles",
        "connector_type": "V40",
        "log_level": "INFO",
        "user_scripts": {"path": "/path/to/scripts", "env_vars": {"name": "value"}},
    }


@pytest.fixture
def example_connector_configuration(example_configuration_dict):
    return example_configuration_dict | {
        "connector_config": {
            "base_url": "https://hoolibot.local",
        },
    }


def test_connector_validator(example_connector_configuration, example_configuration_dict):
    """
    Test that the config validator can be used
    """
    # Should pass
    ConnectorConfig(**example_connector_configuration)
    # Should fail because of an invalid base field
    with pytest.raises(ValidationError):
        ConnectorConfig(**example_connector_configuration | {"location_tz": "La Plata"})
    # Should fail because of an invalid connector specific field
    with pytest.raises(ValidationError):
        ConnectorConfig(
            **example_configuration_dict | {"connector_config": {"missing_fields": True}}
        )
    # Should fail because of a version mismatch
    with pytest.raises(ValidationError):
        ConnectorConfig(**example_configuration_dict | {"connector_type": "Not a real robot"})
    with pytest.raises(ValidationError):
        ConnectorConfig(
            **example_connector_configuration
            | {
                "connector_config": example_connector_configuration["connector_config"]
                | {"base_url": "ftp://hoolibot.local"}
            }
        )
    # Should allow leaving out the user_scripts field. The connector should set it to its default
    default_user_scripts = deepcopy(example_connector_configuration)
    default_user_scripts.pop("user_scripts")
    ConnectorConfig(**default_user_scripts)


def test_takes_values_from_env():
    """
    Test that the config validator can take values from the environment
    """
    mp = pytest.MonkeyPatch()
    mp.setenv("INORBIT_GAUSIUM_BASE_URL", "https://hoolibot.local")
    connector_config = GausiumConnectorConfig()
    assert connector_config.base_url == HttpUrl("https://hoolibot.local")
    # verify empty fields are ignored
    with pytest.raises(ValidationError):
        mp.setenv("INORBIT_GAUSIUM_BASE_URL", "")
        GausiumConnectorConfig()


def test_default_config():
    """
    Test that the default config doesn't have errors
    """
    ConnectorConfig(**default_config)


def test_default_config_matches_example():
    """
    Test that the default config matches the example
    """
    config_path = Path(__file__).parent.parent.parent / "config" / "example.yaml"
    with config_path.open() as f:
        example_config = yaml.safe_load(f)

    assert (
        example_config["my-example-robot"] == default_config
    ), "Default config doesn't match the example"


def test_connector_type_validation():
    """
    Test that the connector type validator works correctly
    """
    # Should pass with valid connector type
    for connector_type in ROBOT_API_CLASSES.keys():
        config = ConnectorConfig(
            inorbit_robot_key="1234567890",
            location_tz="America/Los_Angeles",
            connector_type=connector_type,
            connector_config={"base_url": "https://hoolibot.local"},
        )
        assert config.connector_type == connector_type

    # Should fail with invalid connector type
    with pytest.raises(ValidationError) as excinfo:
        ConnectorConfig(
            inorbit_robot_key="1234567890",
            location_tz="America/Los_Angeles",
            connector_type="InvalidType",
            connector_config={"base_url": "https://hoolibot.local"},
        )
    assert "Unexpected connector type" in str(excinfo.value)
