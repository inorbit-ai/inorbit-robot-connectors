# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import yaml
import os
from typing import Dict, Any
from copy import deepcopy
import logging

logger = logging.getLogger(__name__)


def read_fleet_yaml(config_filename: str) -> Dict[str, Any]:
    """
    Reads a YAML configuration file and returns the complete configuration.

    Args:
        config_filename (str): Path to the YAML configuration file

    Returns:
        Dict[str, Any]: The complete configuration dictionary

    Raises:
        FileNotFoundError: If the configuration file does not exist
        yaml.YAMLError: If the configuration file is not valid YAML
    """
    try:
        with open(config_filename, "r", encoding="utf-8") as file:
            config = yaml.safe_load(file) or {}

        # Expand environment variables in the configuration
        config = _expand_env_vars(config)
        return config

    except FileNotFoundError:
        raise FileNotFoundError(f"Configuration file not found: {config_filename}")
    except yaml.YAMLError as e:
        raise yaml.YAMLError(f"Invalid YAML in configuration file {config_filename}: {e}")


def get_robot_config(config_filename: str, robot_id: str) -> Dict[str, Any]:
    """
    Loads configuration for a specific robot with inheritance from common/fleet_defaults.

    This function supports multiple configuration patterns:
    1. Legacy format: Direct robot configs (backward compatible)
    2. New format with 'common' section: Inherits from 'common'
    3. New format with 'fleet_defaults' section: Inherits from 'fleet_defaults'

    Args:
        config_filename (str): Path to the YAML configuration file
        robot_id (str): The robot ID to load configuration for

    Returns:
        Dict[str, Any]: The robot configuration with inheritance applied

    Raises:
        FileNotFoundError: If the configuration file does not exist
        IndexError: If the robot_id is not found in the configuration
        yaml.YAMLError: If the configuration file is not valid YAML
    """
    full_config = read_fleet_yaml(config_filename)

    # Check if robot exists in configuration
    if robot_id not in full_config:
        available_robots = [
            key for key in full_config.keys() if key not in ["common", "fleet_defaults", "robots"]
        ]
        raise IndexError(
            f"Robot '{robot_id}' not found in configuration. "
            f"Available robots: {available_robots}"
        )

    # Start with empty config
    robot_config = {}

    # Apply inheritance based on configuration structure
    if "common" in full_config:
        # New format with 'common' section
        logger.debug(f"Applying 'common' defaults for robot {robot_id}")
        robot_config = deepcopy(full_config["common"])

    elif "fleet_defaults" in full_config:
        # New format with 'fleet_defaults' section
        logger.debug(f"Applying 'fleet_defaults' for robot {robot_id}")
        robot_config = deepcopy(full_config["fleet_defaults"])

    # Check if robots are in a 'robots' section (hierarchical format)
    if "robots" in full_config and robot_id in full_config["robots"]:
        robot_specific = full_config["robots"][robot_id]
    else:
        # Direct robot configuration (legacy or flat format)
        robot_specific = full_config[robot_id]

    # Merge robot-specific configuration over defaults
    robot_config = _deep_merge(robot_config, robot_specific)

    # Handle connector_config nesting for backward compatibility
    robot_config = _restructure_connector_config(robot_config)

    logger.debug(f"Final configuration for robot {robot_id}: {robot_config}")
    return robot_config


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deep merge two dictionaries, with override values taking precedence.

    Args:
        base (Dict[str, Any]): Base dictionary
        override (Dict[str, Any]): Override dictionary

    Returns:
        Dict[str, Any]: Merged dictionary
    """
    result = deepcopy(base)

    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)

    return result


def _restructure_connector_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Restructures the configuration to match the expected ConnectorConfig format.

    The connector expects certain fields to be nested under 'connector_config',
    particularly MiR-specific settings.

    Args:
        config (Dict[str, Any]): Raw configuration

    Returns:
        Dict[str, Any]: Restructured configuration
    """
    result = deepcopy(config)

    # Fields that should be moved to connector_config
    mir_fields = [
        "mir_host_address",
        "mir_host_port",
        "mir_username",
        "mir_password",
        "mir_api_version",
        "mir_firmware_version",
        "mir_use_ssl",
        "verify_ssl",
        "ssl_ca_bundle",
        "ssl_verify_hostname",
        "enable_temporary_mission_group",
        "default_waypoint_mission_id",
    ]

    # If connector_config doesn't exist, create it
    if "connector_config" not in result:
        result["connector_config"] = {}

    # Move MiR-specific fields to connector_config
    for field in mir_fields:
        if field in result:
            result["connector_config"][field] = result.pop(field)

    # Handle mir_connection section (new format)
    if "mir_connection" in result:
        mir_conn = result.pop("mir_connection")

        # Map new field names to expected names
        field_mapping = {
            "host": "mir_host_address",
            "port": "mir_host_port",
            "username": "mir_username",
            "password": "mir_password",
            "use_ssl": "mir_use_ssl",
        }

        for new_field, old_field in field_mapping.items():
            if new_field in mir_conn:
                result["connector_config"][old_field] = mir_conn[new_field]

        # Copy other SSL fields directly
        ssl_fields = ["verify_ssl", "ssl_ca_bundle", "ssl_verify_hostname"]
        for field in ssl_fields:
            if field in mir_conn:
                result["connector_config"][field] = mir_conn[field]

    # Handle mir_api section (new format)
    if "mir_api" in result:
        mir_api = result.pop("mir_api")
        for field in ["api_version", "firmware_version"]:
            if field in mir_api:
                result["connector_config"][f"mir_{field}"] = mir_api[field]

    # Handle logging section - pass through to InorbitConnectorConfig
    # Supports: log_level, config_file, defaults (including log_file for rotation)
    if "logging" in result:
        # Keep logging section as-is for InorbitConnectorConfig to handle
        # This enables log rotation via defaults.log_file
        pass

    return result


def _expand_env_vars(obj: Any) -> Any:
    """
    Recursively expand environment variables in configuration values.

    Supports ${VAR_NAME} syntax for environment variable substitution.

    Args:
        obj: Configuration object (dict, list, str, or other)

    Returns:
        Configuration object with environment variables expanded
    """
    if isinstance(obj, dict):
        return {key: _expand_env_vars(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [_expand_env_vars(item) for item in obj]
    elif isinstance(obj, str):
        return os.path.expandvars(obj)
    else:
        return obj


def validate_config_structure(config_filename: str) -> Dict[str, Any]:
    """
    Validates the configuration file structure and provides helpful error messages.

    Args:
        config_filename (str): Path to the configuration file

    Returns:
        Dict[str, Any]: Validation results
    """
    try:
        full_config = read_fleet_yaml(config_filename)
    except Exception as e:
        return {
            "valid": False,
            "error": str(e),
            "suggestions": ["Check if the file exists and has valid YAML syntax"],
        }

    validation = {
        "valid": True,
        "structure_type": "unknown",
        "robots": [],
        "has_common_section": False,
        "suggestions": [],
    }

    # Determine configuration structure
    if "common" in full_config or "fleet_defaults" in full_config:
        validation["structure_type"] = "hierarchical"
        validation["has_common_section"] = True

        if "robots" in full_config:
            validation["robots"] = list(full_config["robots"].keys())
        else:
            validation["robots"] = [
                key for key in full_config.keys() if key not in ["common", "fleet_defaults"]
            ]
    else:
        validation["structure_type"] = "flat"
        validation["robots"] = list(full_config.keys())

    # Provide suggestions
    if not validation["has_common_section"]:
        validation["suggestions"].append(
            "Consider adding a 'common' section to reduce configuration duplication"
        )

    if len(validation["robots"]) == 0:
        validation["valid"] = False
        validation["suggestions"].append("No robot configurations found")

    return validation
