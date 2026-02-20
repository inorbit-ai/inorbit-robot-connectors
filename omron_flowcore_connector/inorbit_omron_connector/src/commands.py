# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Collection of command-related models and enums for controlling the FlowCore Fleet."""

# Standard
from enum import StrEnum
from typing import Any, Tuple
from collections.abc import Mapping, Sequence

# Third Party

# InOrbit
from inorbit_connector.commands import CommandModel, ExcludeUnsetMixin
from inorbit_connector.connector import CommandFailure


class CustomScripts(StrEnum):
    """Supported InOrbit CustomScript actions.
    
    These can be invoked via the 'custom_command' action in InOrbit.
    """
    STOP = "stop"
    PAUSE_ROBOT = "pauseRobot"
    RESUME_ROBOT = "resumeRobot"
    DOCK = "dock"
    UNDOCK = "undock"
    SHUTDOWN = "shutdown"
    EXECUTE_MISSION_ACTION = "executeMissionAction"
    CANCEL_MISSION_ACTION = "cancelMissionAction"
    UPDATE_MISSION_ACTION = "updateMissionAction"

class CommandStop(ExcludeUnsetMixin, CommandModel):
    """Command arguments for 'stop' action.
    
    Attributes:
        reason (str): Optional reason for stopping.
    """
    reason: str = "Operator Stop"


def parse_custom_command_args(args: list[Any]) -> Tuple[str, dict[str, Any]]:
    """Parse custom command arguments into script name and parameters.

    Expected format: [script_name, {param1: val1, ...}]
    
    Args:
        args: List of arguments from the InOrbit command.

    Returns:
        Tuple of (script_name, params_dict).

    Raises:
        CommandFailure: If arguments are malformed or missing script name.
    """
    if not args:
        raise CommandFailure(
            execution_status_details="Missing script name",
            stderr="Custom command arguments cannot be empty"
        )
    
    script_name = str(args[0])
    script_args = {}
    
    if len(args) > 1:
        val = args[1]
        if isinstance(val, Mapping):
            script_args = val
        elif isinstance(val, Sequence) and not isinstance(val, str):
            # Handle flat list of key-value pairs [key1, val1, key2, val2]
            # This handles both standard lists and Protobuf RepeatedScalarFieldContainer
            items = val
            if len(items) % 2 != 0:
                 raise CommandFailure(
                    execution_status_details="Invalid arguments format",
                    stderr=f"Expected even number of arguments in list, got {len(items)}"
                )
            script_args = {str(items[i]): items[i+1] for i in range(0, len(items), 2)}
        else:
            # If args[1] is not a dict or list-like, it might be a positional arg style (legacy)
            # For this connector, we enforce structured args for clarity.
            pass

    return script_name, script_args
