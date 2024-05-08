#!/usr/bin/env python
# -*- coding: utf-8 -*-

# TODO(russell): Abstract this into edge-sdk/core

import yaml


def read_yaml(fname: str, robot_id: str = None) -> dict:
    """Load an InOrbit connector config YAML.

    Loads the specified configuration file and returns an object corresponding
    to the given robot_id.

    If no robot_id is provided, the entire configuration
    file is returned.

    If the configuration file is empty, an empty dictionary is returned.

    If the configuration file does not contain the requested robot_id, an
    IndexError is raised.

    Note:
        This function is not thread-safe. It is intended to be called only
        from the main thread.

    Args:
        fname (str): The path to the configuration YAML file.
        robot_id (str): The robot ID to load.

    Returns:
        dict: The configuration file contents.

    Raises:
        FileNotFoundError: If the configuration file does not exist.
        IndexError: If the configuration file does not contain the robot_id.
        yaml.YAMLError: If the configuration file is not valid YAML.
    """

    with open(fname, "r") as file:
        data = yaml.safe_load(file)

        # When the file is empty, data is None
        if not data:
            data = {}

        # If the `robot_id` is not provided return the entire config.
        if not robot_id:
            return data
        # If the `robot_id` is provided, return that config robot.
        elif robot_id in data:
            return data[robot_id]
        # If the `robot_id` is provided but not found, raise an error.
        else:
            raise IndexError(f"Robot ID '{robot_id}' not found in config file")


def write_yaml(fname: str, data: dict) -> None:
    """Write a connector configuration to a YAML file.

    Args:
        fname (str): The path to the configuration YAML file.
        data (dict): The connector configuration data.
    """

    with open(fname, "w") as file:
        yaml.dump(data, file, default_flow_style=False)
