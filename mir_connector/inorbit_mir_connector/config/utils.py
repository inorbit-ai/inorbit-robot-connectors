# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

from ruamel.yaml import YAML

yaml = YAML()
yaml.indent(mapping=2, sequence=4, offset=2)


def read_yaml(config_filename: str, robot_id: str = None) -> dict:
    """
    Loads the configuration file and returns the object corresponding to the given robot_id.
    """

    with open(file=config_filename, mode="r") as f:
        data = yaml.load(f)

        # When the file is empty, data is None
        if not data:
            data = {}

        if not robot_id:
            # If the `robot_id` parameter is not provided return
            # the entire configuration file
            return data
        if robot_id not in data:
            raise IndexError(f"Robot ID '{robot_id}' not found in config file")

        return data[robot_id]


def write_yaml(config_filename: str, config_file_content) -> None:
    """
    Writes configuration file content to the given configuration file.
    """

    with open(file=config_filename, mode="w") as f:
        yaml.dump(config_file_content, f)
