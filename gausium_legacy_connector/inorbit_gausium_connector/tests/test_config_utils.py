# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

from unittest.mock import patch, mock_open

from pydantic import HttpUrl

from inorbit_gausium_connector.src.config.connector_model import load_and_validate, ConnectorConfig


def test_load_and_validate():
    """Test loading and validating a configuration file."""
    yaml_content = """
    robot-id-1:
      inorbit_robot_key: "1234567890"
      location_tz: "America/Los_Angeles"
      connector_type: "V40"
      log_level: "INFO"
      connector_config:
        base_url: "https://hoolibot.local"
    """

    with patch("builtins.open", mock_open(read_data=yaml_content)):
        with patch(
            "inorbit_gausium_connector.src.config.connector_model.read_yaml"
        ) as mock_read_yaml:
            mock_read_yaml.return_value = {
                "inorbit_robot_key": "1234567890",
                "location_tz": "America/Los_Angeles",
                "connector_type": "V40",
                "log_level": "INFO",
                "connector_config": {"base_url": "https://hoolibot.local"},
            }

            config = load_and_validate("dummy_path.yaml", "robot-id-1")
            assert isinstance(config, ConnectorConfig)
            assert config.inorbit_robot_key == "1234567890"
            assert config.location_tz == "America/Los_Angeles"
            assert config.connector_type == "V40"
            assert config.log_level.value == "INFO"
            assert config.connector_config.base_url == HttpUrl("https://hoolibot.local")
