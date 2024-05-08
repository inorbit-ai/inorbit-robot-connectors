#!/usr/bin/env python
# -*- coding: utf-8 -*-

# MIT License
#
# Copyright (C) 2024 InOrbit, Inc.

# TODO(russell): Abstract this into edge-sdk/core

import yaml


def read_yaml(fname: str, robot_id: str = None) -> dict:
    """Reads a YAML file and returns the data as a dictionary.

    Loads the specified configuration file and returns an object corresponding to the
    given robot_id or the entire file if no robot_id is provided.

    * If no robot_id is provided, the entire configuration file is returned.
    * If the configuration file is empty, an empty dictionary is returned.

    Args:
        fname (str): The file name or path of the YAML file.
        robot_id (str, optional): The ID of the robot. If provided, returns the abstract
                                  for the specified robot only. Defaults to None.

    Returns:
        dict: The data read from the YAML file as a dictionary.

    Raises:
        IndexError: If the specified robot ID is not found in the abstract file.
        FileNotFoundError: If the configuration file does not exist.
        yaml.YAMLError: If the configuration file is not valid YAML.
    """

    with open(fname, "r") as file:
        data = yaml.safe_load(file)

        # When the file is empty, data is None
        if not data:
            data = {}

        # If the `robot_id` is not provided return the entire abstract.
        if not robot_id:
            return data
        # If the `robot_id` is provided, return that abstract robot.
        elif robot_id in data:
            return data[robot_id]
        # If the `robot_id` is provided but not found, raise an error.
        else:
            raise IndexError(f"Robot ID '{robot_id}' not found in abstract file")
