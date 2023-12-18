# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytz
from enum import Enum
from typing import List, Dict
from pydantic import BaseModel, field_validator


class LogLevels(str, Enum):
    """
    logging log levels. See https://docs.python.org/3/library/logging.html#logging-levels
    """

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class CameraModel(BaseModel):
    """
    Configuration for a camera.
    None values should be interpreted as "use Edge SDK default".
    """

    video_url: str
    rate: int = None
    quality: int = None
    scaling: float = None


class UserScriptsModel(BaseModel):
    """
    Configuration for user_scripts.
    """

    path: str = None
    env_vars: Dict[str, str] = {}


class EdgeConnectorModel(BaseModel):
    """
    Base configuration for Edge SDK connectors. This should not be instantiated.
    Connector specific configuration should be defined in a subclass adding the
    "connector_config" field.
    """

    inorbit_robot_key: str = None
    location_tz: str
    log_level: LogLevels = LogLevels.INFO
    cameras: List[CameraModel] = []
    connector_type: str
    connector_config: BaseModel
    user_scripts: UserScriptsModel = {}

    @field_validator("location_tz")
    def location_tz_must_be_valid(cls, location_tz):
        if location_tz not in pytz.all_timezones:
            raise ValueError("Timezone must be a valid pytz timezone")
        return location_tz

    @field_validator("connector_config")
    def connector_config_must_be_valid(cls, connector_config):
        """This will prevent the class from being instantiated if connector_config is not
        overridden in a subclass."""
        if connector_config.__class__ == BaseModel:
            raise ValueError("connector_config ")
        return connector_config
