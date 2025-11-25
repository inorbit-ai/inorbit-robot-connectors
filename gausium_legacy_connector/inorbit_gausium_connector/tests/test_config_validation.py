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


class TestConfigValidation:
    """Tests for configuration validation functionality."""

    @pytest.fixture
    def example_configuration_dict(self):
        return {
            "inorbit_robot_key": "1234567890",
            "location_tz": "America/Los_Angeles",
            "connector_type": "V40",
            "log_level": "INFO",
            "user_scripts": {"path": "/path/to/scripts", "env_vars": {"name": "value"}},
        }

    @pytest.fixture
    def example_connector_configuration(self, example_configuration_dict):
        return example_configuration_dict | {
            "connector_config": {
                "base_url": "https://hoolibot.local",
            },
        }

    def test_connector_validator(self, example_connector_configuration, example_configuration_dict):
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
        # Should allow leaving out the user_scripts field.
        # The connector should set it to its default
        default_user_scripts = deepcopy(example_connector_configuration)
        default_user_scripts.pop("user_scripts")
        ConnectorConfig(**default_user_scripts)

    def test_ignore_model_type_validation(self):
        """
        Test that the ignore_model_type_validation field is properly validated
        """
        # Default value should be False
        config = ConnectorConfig(
            inorbit_robot_key="1234567890",
            location_tz="America/Los_Angeles",
            connector_type="V40",
            connector_config={"base_url": "https://hoolibot.local"},
        )
        assert hasattr(config.connector_config, "ignore_model_type_validation")
        assert config.connector_config.ignore_model_type_validation is False

        # Explicitly set to True
        config = ConnectorConfig(
            inorbit_robot_key="1234567890",
            location_tz="America/Los_Angeles",
            connector_type="V40",
            connector_config={
                "base_url": "https://hoolibot.local",
                "ignore_model_type_validation": True,
            },
        )
        assert config.connector_config.ignore_model_type_validation is True

        # Explicitly set to False
        config = ConnectorConfig(
            inorbit_robot_key="1234567890",
            location_tz="America/Los_Angeles",
            connector_type="V40",
            connector_config={
                "base_url": "https://hoolibot.local",
                "ignore_model_type_validation": False,
            },
        )
        assert config.connector_config.ignore_model_type_validation is False

    def test_takes_values_from_env(self):
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

    def test_ignore_model_type_validation_from_env(self):
        """
        Test that the ignore_model_type_validation field can be set from environment variables
        """
        mp = pytest.MonkeyPatch()
        mp.setenv("INORBIT_GAUSIUM_BASE_URL", "https://hoolibot.local")

        # Test default value (False)
        connector_config = GausiumConnectorConfig()
        assert connector_config.ignore_model_type_validation is False

        # Test setting to True via environment
        mp.setenv("INORBIT_GAUSIUM_IGNORE_MODEL_TYPE_VALIDATION", "true")
        connector_config = GausiumConnectorConfig()
        assert connector_config.ignore_model_type_validation is True

        # Test setting to False via environment
        mp.setenv("INORBIT_GAUSIUM_IGNORE_MODEL_TYPE_VALIDATION", "false")
        connector_config = GausiumConnectorConfig()
        assert connector_config.ignore_model_type_validation is False

    def test_default_config(self):
        """
        Test that the default config doesn't have errors
        """
        ConnectorConfig(**default_config)

    def test_default_config_matches_example(self):
        """
        Test that the default config matches the example
        """
        config_path = Path(__file__).parent.parent.parent / "config" / "example.yaml"
        with config_path.open() as f:
            example_config = yaml.safe_load(f)

        # Update the example config to match the new logging schema
        example_config["my-example-robot"]["logging"] = {
            "log_level": "INFO",
        }

        assert (
            example_config["my-example-robot"] == default_config
        ), "Default config doesn't match the example"

    def test_connector_type_validation(self):
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
