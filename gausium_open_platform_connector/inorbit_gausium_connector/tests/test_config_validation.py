# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import tempfile
from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from inorbit_gausium_connector.config.connector_model import ConnectorConfig
from inorbit_gausium_connector.config.connector_model import default_config
from inorbit_gausium_connector.config.connector_model import PhantasConnectorConfig
from pydantic import HttpUrl
from pydantic import ValidationError


@pytest.fixture
def temp_scripts_dir():
    """Create a temporary directory for user scripts."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    # Cleanup
    import shutil

    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def example_configuration_dict(temp_scripts_dir):
    return {
        "inorbit_robot_key": "1234567890",
        "location_tz": "America/Los_Angeles",
        "connector_type": "Gausium Phantas S",
        "logging": {"log_level": "INFO"},
        "user_scripts_dir": temp_scripts_dir,
        "env_vars": {"name": "value"},
    }


@pytest.fixture
def example_connector_configuration(example_configuration_dict):
    return example_configuration_dict | {
        "connector_config": {
            "base_url": "https://hoolibot.local",
            "serial_number": "GS000-0000-000-0000",
            "client_id": "inorbit",
            "client_secret": "orbito",
            "access_key_secret": "otibro",
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
    # Should allow leaving out the user_scripts_dir field.
    # The connector should set it to its default
    default_user_scripts = deepcopy(example_connector_configuration)
    default_user_scripts.pop("user_scripts_dir", None)
    ConnectorConfig(**default_user_scripts)


def test_takes_values_from_env():
    """
    Test that the config validator can take values from the environment
    """
    mp = pytest.MonkeyPatch()
    mp.setenv("INORBIT_GAUSIUM_BASE_URL", "https://hoolibot.local")
    mp.setenv("INORBIT_GAUSIUM_SERIAL_NUMBER", "GS000-0000-000-0000")
    mp.setenv("INORBIT_GAUSIUM_CLIENT_ID", "inorbit")
    mp.setenv("INORBIT_GAUSIUM_CLIENT_SECRET", "orbito")
    mp.setenv("INORBIT_GAUSIUM_ACCESS_KEY_SECRET", "otibro")
    connector_config = PhantasConnectorConfig()
    assert connector_config.base_url == HttpUrl("https://hoolibot.local")
    assert connector_config.serial_number == "GS000-0000-000-0000"
    assert connector_config.client_id == "inorbit"
    assert connector_config.client_secret == "orbito"
    assert connector_config.access_key_secret == "otibro"
    # verify empty fields are ignored
    with pytest.raises(ValidationError):
        mp.setenv("INORBIT_GAUSIUM_SERIAL_NUMBER", "")
        PhantasConnectorConfig()


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
