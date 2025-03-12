# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest
from unittest.mock import patch, Mock
from pydantic import HttpUrl

from inorbit_gausium_connector.src.robot.robot_api import GausiumCloudAPI


class TestModelTypeValidation:
    """Tests for model type validation functionality in GausiumCloudAPI."""

    @pytest.fixture
    def mock_robot_api(self):
        api = GausiumCloudAPI(
            base_url=HttpUrl("http://example.com/"),
            allowed_model_types=["VC 40 Pro"],
            loglevel="DEBUG",
        )

        # Mock components to prevent actual HTTP requests
        api.logger = Mock()
        api.api_session = Mock()
        api._device_status = {}

        return api

    @pytest.fixture
    def mock_get_method(self):
        """Mock the _get method to avoid actual HTTP requests."""
        with patch.object(GausiumCloudAPI, "_get") as mock_get:
            yield mock_get

    @pytest.fixture
    def mock_robot_info_success(self, mock_get_method):
        """Mock a successful robot info API call with a valid model type."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": {"modelType": "VC 40 Pro", "softwareVersion": "1.0.0"}
        }
        mock_get_method.return_value = mock_response
        return mock_response

    @pytest.fixture
    def mock_robot_info_invalid(self, mock_get_method):
        """Mock a robot info API call with an invalid model type."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": {"modelType": "Invalid Model", "softwareVersion": "1.0.0"}
        }
        mock_get_method.return_value = mock_response
        return mock_response

    @pytest.fixture
    def mock_position_data(self, mock_get_method):
        """Mock position data API call."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "worldPosition": {"position": {"x": 1.0, "y": 2.0}, "orientation": {"z": 90.0}}
        }
        mock_get_method.return_value = mock_response
        return mock_response

    @pytest.fixture
    def mock_device_status(self, mock_get_method):
        """Mock device status API call."""
        mock_response = Mock()
        mock_response.json.return_value = {"data": {"battery": 80}}
        mock_get_method.return_value = mock_response
        return mock_response

    def test_update_with_valid_model_type(self, mock_robot_api, mock_robot_info_success):
        """Test that update() succeeds when the robot reports a valid model type."""
        # Need to patch both necessary methods called in update()
        with patch.object(
            mock_robot_api, "_get_robot_info", return_value={"data": {"modelType": "VC 40 Pro"}}
        ), patch.object(
            mock_robot_api, "_get_device_status", return_value={"data": {"battery": 80}}
        ), patch.object(
            mock_robot_api,
            "_fetch_position",
            return_value={
                "worldPosition": {"position": {"x": 1.0, "y": 2.0}, "orientation": {"z": 90.0}}
            },
        ):
            # This should not raise an exception
            mock_robot_api.update()

    def test_update_with_invalid_model_type(self, mock_robot_api, mock_robot_info_invalid):
        """Test that update() raises ValueError when the robot reports an invalid model type."""
        # Need to patch all necessary methods called in update() before the validation happens
        with patch.object(
            mock_robot_api,
            "_get_robot_info",
            return_value={"data": {"modelType": "Invalid Model"}},
        ), patch.object(
            mock_robot_api, "_get_device_status", return_value={"data": {"battery": 80}}
        ), patch.object(
            mock_robot_api,
            "_fetch_position",
            return_value={
                "worldPosition": {"position": {"x": 1.0, "y": 2.0}, "orientation": {"z": 90.0}}
            },
        ):
            # This should raise a ModelTypeMismatchError
            with pytest.raises(Exception) as excinfo:
                mock_robot_api.update()

            # Check the error message
            error_msg = str(excinfo.value)
            assert "is not supported by the API wrapper" in error_msg
            assert "VC 40 Pro" in error_msg

    def test_no_validation_when_allowed_model_types_empty(
        self, mock_robot_api, mock_robot_info_invalid
    ):
        """Test that no validation occurs when allowed_model_types is empty."""
        # Set allowed_model_types to empty list
        mock_robot_api._allowed_model_types = []

        # Patch all necessary methods called in update()
        with patch.object(
            mock_robot_api,
            "_get_robot_info",
            return_value={"data": {"modelType": "Invalid Model"}},
        ), patch.object(
            mock_robot_api, "_get_device_status", return_value={"data": {"battery": 80}}
        ), patch.object(
            mock_robot_api,
            "_fetch_position",
            return_value={
                "worldPosition": {"position": {"x": 1.0, "y": 2.0}, "orientation": {"z": 90.0}}
            },
        ):
            # This should not raise an exception despite invalid model type
            mock_robot_api.update()

    def test_explicit_ignore_model_type_validation(self, mock_get_method):
        """Test that validation can be explicitly bypassed using empty allowed_model_types."""
        # Create API with empty allowed_model_types list (which effectively ignores validation)
        api = GausiumCloudAPI(
            base_url=HttpUrl("http://example.com/"),
            allowed_model_types=[],  # Empty list means no validation
            loglevel="DEBUG",
        )

        # Mock components to prevent actual HTTP requests
        api.logger = Mock()
        api.api_session = Mock()
        api._device_status = {}

        # Setup API call responses with an invalid model type
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": {"modelType": "Some Totally Invalid Model", "softwareVersion": "1.0.0"}
        }
        mock_get_method.return_value = mock_response

        # Patch necessary methods for update()
        with patch.object(
            api,
            "_get_robot_info",
            return_value={"data": {"modelType": "Some Totally Invalid Model"}},
        ), patch.object(
            api, "_get_device_status", return_value={"data": {"battery": 80}}
        ), patch.object(
            api,
            "_fetch_position",
            return_value={
                "worldPosition": {"position": {"x": 1.0, "y": 2.0}, "orientation": {"z": 90.0}}
            },
        ):
            # This should not raise an exception despite the invalid model type
            api.update()

            # Success if we reach here without exception
