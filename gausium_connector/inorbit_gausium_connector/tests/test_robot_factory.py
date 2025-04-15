# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest
from unittest.mock import patch
from pydantic import HttpUrl

from inorbit_gausium_connector.src.robot import Vaccum40RobotAPI
from inorbit_gausium_connector.src.robot.robot_factory import (
    create_robot,
    ROBOT_API_CLASSES,
    CLOUD_APIS_ALLOWED_MODEL_TYPES,
)


class TestRobotFactory:
    """Tests for the robot factory functionality."""

    def test_robot_api_classes(self):
        """Test that the ROBOT_API_CLASSES dictionary contains the expected mappings."""
        assert "V40" in ROBOT_API_CLASSES
        assert ROBOT_API_CLASSES["V40"] == Vaccum40RobotAPI

    def test_create_robot_api_with_valid_type(self):
        """Test creating a robot API with a valid connector type."""
        with patch.object(Vaccum40RobotAPI, "__init__", return_value=None) as mock_init:
            api = create_robot(
                connector_type="V40", base_url=HttpUrl("http://example.com/"), loglevel="DEBUG"
            )
            mock_init.assert_called_once_with(
                base_url=HttpUrl("http://example.com/"),
                loglevel="DEBUG",
                allowed_model_types=CLOUD_APIS_ALLOWED_MODEL_TYPES["V40"],
            )
            assert isinstance(api, Vaccum40RobotAPI)

    def test_create_robot_api_with_invalid_type(self):
        """Test creating a robot API with an invalid connector type."""
        with pytest.raises(ValueError) as excinfo:
            create_robot(
                connector_type="InvalidType",
                base_url=HttpUrl("http://example.com/"),
                loglevel="INFO",
            )
        assert "Unsupported connector_type: InvalidType" in str(excinfo.value)
        # Check that the error message includes all supported types
        for robot_type in ROBOT_API_CLASSES.keys():
            assert robot_type in str(excinfo.value)

    def test_create_robot_api_default_loglevel(self):
        """Test creating a robot API with the default log level."""
        with patch.object(Vaccum40RobotAPI, "__init__", return_value=None) as mock_init:
            api = create_robot(connector_type="V40", base_url=HttpUrl("http://example.com/"))
            mock_init.assert_called_once_with(
                base_url=HttpUrl("http://example.com/"),
                loglevel="INFO",
                allowed_model_types=CLOUD_APIS_ALLOWED_MODEL_TYPES["V40"],
            )
            assert isinstance(api, Vaccum40RobotAPI)

    def test_allowed_model_types_validation(self):
        """Test the allowed model types validation functionality."""
        # Create a mock robot API with allowed model types
        with patch.object(Vaccum40RobotAPI, "__init__", return_value=None) as mock_init:
            # Create with default validation (not ignored)
            api = create_robot(
                connector_type="V40",
                base_url=HttpUrl("http://example.com/"),
            )
            # Check that the allowed model types were passed correctly
            mock_init.assert_called_with(
                base_url=HttpUrl("http://example.com/"),
                loglevel="INFO",
                allowed_model_types=CLOUD_APIS_ALLOWED_MODEL_TYPES["V40"],
            )
            assert isinstance(api, Vaccum40RobotAPI)

        # Test with validation ignored
        with patch.object(Vaccum40RobotAPI, "__init__", return_value=None) as mock_init:
            api = create_robot(
                connector_type="V40",
                base_url=HttpUrl("http://example.com/"),
                ignore_model_type_validation=True,
            )
            # Check that empty allowed model types were passed
            mock_init.assert_called_with(
                base_url=HttpUrl("http://example.com/"), loglevel="INFO", allowed_model_types=[]
            )
            assert isinstance(api, Vaccum40RobotAPI)
