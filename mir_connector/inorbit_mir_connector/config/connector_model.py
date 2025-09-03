# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

from pydantic import field_validator, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from inorbit_connector.models import InorbitConnectorConfig
from inorbit_connector.utils import read_yaml
from typing import Optional

# Default environment file, relative to the directory the connector is executed from. If using a
# different .env file, make sure to source it before running the connector.
DEFAULT_ENV_FILE = "config/.env"

# Expected values
CONNECTOR_TYPES = ["MiR100", "MiR250"]
FIRMWARE_VERSIONS = ["v2", "v3"]
MIR_API_VERSION = "v2.0"


class MirConnectorConfig(BaseSettings):
    """
    Specific configuration for MiR connector.
    If any field is missing, the initializer will attempt to replace it by reading from the
    environment. Every field can be ignored if set in the env with the prefix INORBIT_MIR_
    (e.g. mir_host_address -> INORBIT_MIR_MIR_HOST_ADDRESS)
    """

    model_config = SettingsConfigDict(
        env_prefix="INORBIT_MIR_",
        env_ignore_empty=True,
        case_sensitive=False,
        env_file=DEFAULT_ENV_FILE,
        extra="allow",
    )

    mir_host_address: str
    mir_host_port: int

    mir_username: str
    mir_password: str
    mir_api_version: str
    mir_firmware_version: str
    enable_mission_tracking: bool

    # SSL Configuration
    mir_use_ssl: bool
    verify_ssl: bool = True  # Verify SSL certificates (set to False for self-signed)
    ssl_ca_bundle: Optional[str] = None  # Path to CA bundle file for custom CAs
    ssl_verify_hostname: bool = (
        True  # Verify hostname matches certificate (set to False for FRP/proxy)
    )

    @field_validator("mir_api_version")
    def api_version_validation(cls, mir_api_version):
        if mir_api_version != MIR_API_VERSION:
            raise ValueError(
                f"Unexpected MiR API version '{mir_api_version}'. Expected '{MIR_API_VERSION}'"
            )
        return mir_api_version

    @field_validator("mir_firmware_version")
    def firmware_version_validation(cls, mir_firmware_version):
        if mir_firmware_version not in FIRMWARE_VERSIONS:
            raise ValueError(
                f"Unexpected MiR firmware version '{mir_firmware_version}'. "
                f"Expected one of '{FIRMWARE_VERSIONS}'"
            )
        return mir_firmware_version


class ConnectorConfig(InorbitConnectorConfig):
    """
    MiR connector configuration schema.
    """

    connector_config: MirConnectorConfig

    @field_validator("connector_type")
    def connector_type_validation(cls, connector_type):
        if connector_type not in CONNECTOR_TYPES:
            raise ValueError(
                f"Unexpected connector type '{connector_type}'. Expected one of '{CONNECTOR_TYPES}'"
            )
        return connector_type


def load_and_validate(config_filename: str, robot_id: str) -> ConnectorConfig:
    """Loads and validates the configuration file.

    Raises an exception if the arguments or configuration are invalid.

    Args:
        config_filename (str): The YAML file to load the configuration from.
        robot_id (str): The InOrbit robot ID for robot to load the configuration for.

    Returns:
        ConnectorConfig: The configuration object with the loaded values.

    Raises:
        FileNotFoundError: If the configuration file does not exist.
        IndexError: If the configuration file does not contain the robot_id.
        yaml.YAMLError: If the configuration file is not valid YAML.
        ValidationError: If the configuration file is not valid.
    """

    config = read_yaml(config_filename, robot_id)
    return ConnectorConfig(**config)


def format_validation_error(error: ValidationError) -> str:
    """Format Pydantic validation errors into a user-friendly message."""
    error_messages = []

    for err in error.errors():
        field_path = " -> ".join(str(loc) for loc in err["loc"])
        error_msg = err["msg"]

        if field_path:
            error_messages.append(f"  • Field '{field_path}': {error_msg}")
        else:
            error_messages.append(f"  • {error_msg}")

    return "Config validation failed:\n" + "\n".join(error_messages)
