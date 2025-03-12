# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

from inorbit_connector.connector import Connector
from inorbit_edge.robot import COMMAND_CUSTOM_COMMAND
from inorbit_edge.robot import COMMAND_MESSAGE
from inorbit_edge.robot import COMMAND_NAV_GOAL

from inorbit_gausium_connector.src.robot.robot_api import ModelTypeMismatchError

from .. import __version__
from .config.connector_model import ConnectorConfig
from .robot import create_robot_api


class GausiumConnector(Connector):
    """Gausium connector.

    This class handles by-directional interaction between a Gausium robot and
    the InOrbit platform using the InOrbit python EdgeSDK.

    Arguments:
        robot_id (str): The ID of the Gausium robot.
        config (ConnectorConfig): The configuration object for the Gausium Connector.
    """

    def __init__(self, robot_id: str, config: ConnectorConfig) -> None:
        """Initialize the Gausium Connector."""
        super().__init__(robot_id, config)
        self.robot_api = create_robot_api(
            connector_type=config.connector_type,
            base_url=config.connector_config.base_url,
            loglevel=config.log_level.value,
            ignore_model_type_validation=config.connector_config.ignore_model_type_validation,
        )
        self.status = {}

    def _connect(self) -> None:
        """Connect to the robot services.

        This method should always call super.
        """
        super()._connect()

    def _execution_loop(self) -> None:
        """The main execution loop for the connector.

        This is where the meat of your connector is implemented. It is good practice to
        handle things like action requests in a threaded manner so that the connector
        does not block the execution loop.
        """

        # Update the robot data
        # If case of a model type mismatch, raise an exception so that the connector is stopped.
        # Otherwise, log the error and continue.
        try:
            self.robot_api.update()
        except ModelTypeMismatchError as ex:
            raise ex
        except Exception as ex:
            self._logger.error(f"Failed to refresh robot data: {ex}")
            return

        self.publish_pose(**self.robot_api.pose)
        self._robot_session.publish_odometry(**self.robot_api.odometry)
        self._robot_session.publish_key_values(
            {
                **self.robot_api.key_values,
                "connector_version": __version__,
            }
        )

    def _inorbit_command_handler(self, command_name, args, options):
        """Callback method for command messages.

        The callback signature is `callback(command_name, args, options)`

        Arguments:
            command_name -- identifies the specific command to be executed
            args -- is an ordered list with each argument as an entry. Each
                element of the array can be a string or an object, depending on
                the definition of the action.
            options -- is a dictionary that includes:
                - `result_function` can be called to report command execution result.
                It has the following signature: `result_function(return_code)`.
                - `progress_function` can be used to report command output and has
                the following signature: `progress_function(output, error)`.
                - `metadata` is reserved for the future and will contains additional
                information about the received command request.
        """
        if command_name == COMMAND_CUSTOM_COMMAND:
            self._logger.info(f"Received '{command_name}'!. {args}")
            if not self.is_robot_available():
                self._logger.error("Robot is unavailable")
                return options["result_function"]("1", "Robot is not available")

            # Parse command name and arguments
            # script_name = args[0]
            args_raw = list(args[1])
            script_args = {}
            if (
                isinstance(args_raw, list)
                and len(args_raw) % 2 == 0
                and all(isinstance(key, str) for key in args_raw[::2])
            ):
                script_args = dict(zip(args_raw[::2], args_raw[1::2]))
                self._logger.debug(f"Parsed arguments are: {script_args}")
            else:
                return options["result_function"]("1", "Invalid arguments")

            # if script_name == ...:
            #     pass
            # else:
            #     # Other kind if custom commands may be handled by the edge-sdk (e.g. user_scripts)
            #     # and not by the connector code itself
            #     # Do not return any result and leave it to the edge-sdk to handle it
            #     return

            # Return '0' for success
            return options["result_function"]("0")

        elif command_name == COMMAND_NAV_GOAL:
            self._logger.info(f"Received '{command_name}'!. {args}")
            pose = args[0]
            self.robot_api.send_waypoint(pose)

        elif command_name == COMMAND_MESSAGE:
            return options["result_function"]("1", f"'{COMMAND_MESSAGE}' is not implemented")

        else:
            self._logger.info(f"Received '{command_name}'!. {args}")

    def is_robot_available(self) -> bool:
        """Check if the robot is available for receiving commands.

        Returns:
            bool: True if the robot is online, False otherwise.
        """
        # If the last call was successful and the robot is online, return True
        # If unable to determine if the robot is online from the status data, assume it is
        return self.robot_api._last_call_successful and self.status.get("online", True)
