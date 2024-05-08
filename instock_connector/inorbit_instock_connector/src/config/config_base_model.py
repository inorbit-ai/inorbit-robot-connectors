#!/usr/bin/env python
# -*- coding: utf-8 -*-

# TODO(russell): Abstract this file into edge-sdk/core

import pytz

from enum import Enum
from typing import List
from pydantic import BaseModel, field_validator

# The default timezone to use if no timezone is supplied.
DEFAULT_TIMEZONE = "UTC"


class LogLevels(str, Enum):
    """Log levels for logging.

    See https://docs.python.org/3/library/logging.html#logging-levels
    """

    # TODO(russell): docstrings
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class CameraModel(BaseModel):
    """Configuration for a camera.

    None values should be interpreted as "use Edge SDK default".
    """

    # TODO(russell): docstrings
    video_url: str
    # TODO(tomi): if missing, do not pass it as an argument to openCV and
    #             instead let it use the default
    rate: int = None
    quality: int = None
    scaling: float = None


class EdgeConnectorModel(BaseModel):
    """Base configuration for Edge SDK connectors.

    This should not be instantiated. Connector specific configuration should be
    defined in a subclass adding the "connector_config" field.
    """

    # TODO(russell): docstrings
    inorbit_robot_key: str = None
    location_tz: str = "UTC"
    log_level: LogLevels = LogLevels.INFO
    user_scripts_dir: str = "./user_scripts"
    cameras: List[CameraModel] = []
    connector_type: str
    connector_config: BaseModel
    # Update frequency in Hz
    connector_update_freq: float = 1.0

    # noinspection PyMethodParameters
    @field_validator("location_tz")
    def location_tz_must_exist(cls, location_tz: str) -> str:
        """Validate the timezone exists in the pytz package.

        Args:
            location_tz (str): The timezone string to validate.

        Returns:
            str: The validated timezone string.

        Raises:
            ValueError: Raised if the timezone does not exist in pytz.
        """

        if location_tz not in pytz.all_timezones:
            raise ValueError("Timezone must be a valid pytz timezone")
        return location_tz

    # noinspection PyMethodParameters
    @field_validator("connector_config")
    def connector_config_check(cls, connector_config: BaseModel) -> BaseModel:
        """Validate the configuration is not just the BaseModel.

        This will prevent the class from being instantiated if connector_config
        is not overridden in a subclass.

        Args:
            connector_config (BaseModel): The subclass of the BaseModel.

        Returns:
            BaseModel: The validated BaseModel subclass.

        Raises:
            ValueError: Raised if `connector_config` is just a BaseModel class.
        """

        if connector_config.__class__ == BaseModel:
            raise ValueError("No subclass of BaseModel found")
        return connector_config
