#!/usr/bin/env python
# -*- coding: utf-8 -*-

# MIT License
#
# Copyright (C) 2024 InOrbit, Inc.

# Standard
import logging
import os
import threading
from time import sleep

# Third Party
from inorbit_edge.robot import INORBIT_CLOUD_SDK_ROBOT_CONFIG_URL, RobotSession
from inorbit_edge.video import OpenCVCamera
from pydantic import BaseModel

from inorbit_instock_connector.src.abstract import InorbitConnectorModel


# TODO(russell): This could be abstracted at the SDK level.
class RobotSessionModel(BaseModel):
    """Configuration for an InOrbit robot session."""

    robot_id: str
    robot_name: str
    robot_key: str | None = None
    use_ssl: bool = os.environ.get("INORBIT_USE_SSL", "true").lower() == "true"
    # This will raise if not found or provided
    api_key: str = os.environ["INORBIT_API_TOKEN"]
    # This will default to None if not found or provided
    endpoint: str = os.environ.get(
        "INORBIT_API_URL",
        INORBIT_CLOUD_SDK_ROBOT_CONFIG_URL,
    )


# TODO(russell): Some of this could be abstracted at the SDK level.
class Connector:
    """Generic InOrbit connector.

    TODO(russell): Longer description.

    This class handles bi-directional communication with InOrbit.
    """

    def __init__(self, robot_id: str, config: InorbitConnectorModel) -> None:
        """Initialize a new InOrbit connector.

        TODO(russell): Longer description.

        Args:
            robot_id (str): The ID of the InOrbit robot.
            config (InorbitConnectorModel): The configuration for the connector.
        """

        # Threading for the main run methods
        self.__stop_event = threading.Event()
        self.__thread = threading.Thread(target=self.__run)

        # Logging information
        self._logger = logging.getLogger(__name__)
        self._logger.setLevel(config.log_level.value)

        self.user_scripts_dir = config.user_scripts_dir

        self.robot_id = robot_id
        self.config = config

        # Create the robot session in InOrbit
        robot_session_config = RobotSessionModel(
            robot_id=robot_id,
            robot_name=robot_id,
            robot_api_key=config.api_token,
        )

        self._robot_session = RobotSession(**robot_session_config.model_dump())

    def connect(self) -> None:
        """Connect to any external services.

        The base method handles connecting to InOrbit based on the provided
        configuration. Subclasses should override this method to connect to any
        external services ensuring to call the super method as well.

        This method should not be called directly. Instead, call the start() method to
        start the connector. This ensures that the connector is only started once.
        """

        # Connect to InOrbit
        self._robot_session.connect()

    def start(self) -> None:
        """Start the execution loop of this connector.

        This method should be called to start the execution loop of this connector, will
        block until the execution loop is started but run the loop on a new thread, and
        will also call connect() to connect to any external services.
        """

        # Prevent starting already running thread
        if not self.__thread.is_alive():
            self.__stop_event.clear()

            # Connect to external services and create the InOrbit session
            self.connect()

            # Set up camera feeds
            for idx, camera_config in enumerate(self.config.cameras):
                self._logger.debug(
                    f"Registering camera {idx}:\n{camera_config.model_dump()}"
                )
                self._robot_session.register_camera(
                    str(idx), OpenCVCamera(**camera_config.model_dump())
                )

            # Create new thread if an old thread finished
            self.__thread = threading.Thread(target=self.__run)
            self.__thread.start()

    def disconnect(self) -> None:
        """Disconnect from any external services.

        The base method handles disconnecting from InOrbit based on the provided
        configuration. Subclasses should override this method to disconnect from any
        external services ensuring to call the super method as well.

        This method should not be called directly. Instead, call the stop() method to
        stop the connector. This ensures that the connector is only stopped once.
        """

        # Disconnect from InOrbit
        self._robot_session.disconnect()

    def stop(self) -> None:
        """Stop the execution loop of this connector.

        This method should be called to stop the execution loop of this connector, will
        block until the execution loop is stopped, and will call disconnect() to clean
        up any external connections.
        """

        # Stop the execution loop
        self.__stop_event.set()
        self.__thread.join()

        # Cleanup external connections
        self.disconnect()

    def __run(self) -> None:
        """The main run thread method for the connector."""

        while not self.__stop_event.is_set():
            self.execution_loop()
            sleep(self.config.connector_update_freq)

    # noinspection PyMethodMayBeStatic
    def execution_loop(self) -> None:
        """The main execution loop for the connector.

        This method should be overridden by subclasses to provide the execution loop for
        the connector, will be called repeatedly until the connector is stopped, and
        should not be called directly. Instead, call the start() or stop() methods to
        start or stop the connector. This ensures that the connector is only started or
        stopped once.
        """

        # Overwrite this in subclass to something useful
        logging.warning("Execution loop is empty.")

    def get_logger(self) -> logging.Logger:
        return self._logger

    def get_robot_session(self) -> RobotSession:
        return self._robot_session
