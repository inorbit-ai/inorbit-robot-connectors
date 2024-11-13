# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest
from inorbit_mir_connector.config.mir100_model import MiR100Config
from pydantic import ValidationError
from copy import deepcopy


@pytest.fixture
def example_configuration_dict():
    return {
        "inorbit_robot_key": "1234567890",
        "location_tz": "America/Los_Angeles",
        "connector_type": "mir100",
        "log_level": "INFO",
        "user_scripts": {"path": "/path/to/scripts", "env_vars": {"name": "value"}},
    }


@pytest.fixture
def example_mir100_configuration_dict(example_configuration_dict):
    return example_configuration_dict | {
        "connector_config": {
            "mir_host_address": "localhost",
            "mir_host_port": 80,
            "mir_enable_ws": True,
            "mir_ws_port": 9090,
            "mir_use_ssl": False,
            "mir_username": "admin",
            "mir_password": "admin",
            "mir_api_version": "v2.0",
            "enable_mission_tracking": True,
        },
    }


def test_mir100_validator(example_mir100_configuration_dict, example_configuration_dict):
    """
    Test that the mir100 config validator can be used
    """
    # Should pass
    MiR100Config(**example_mir100_configuration_dict)
    # Should fail because of an invalid base field
    with pytest.raises(ValidationError):
        MiR100Config(**example_mir100_configuration_dict | {"location_tz": "La Plata"})
    # Should fail because of an invalid mir100 specific field
    with pytest.raises(ValidationError):
        MiR100Config(**example_configuration_dict | {"connector_config": {"missing_fields": True}})
    # Should fail because of a version mismatch
    with pytest.raises(ValidationError):
        MiR100Config(**example_mir100_configuration_dict | {"connector_type": "001rim"})
    with pytest.raises(ValidationError):
        MiR100Config(
            **example_mir100_configuration_dict
            | {
                "connector_config": example_mir100_configuration_dict["connector_config"]
                | {"mir_api_version": "v1.0"}
            }
        )
    # Should allow leaving out the user_scripts field. The connector should set it to its default
    broken_config = deepcopy(example_mir100_configuration_dict)
    broken_config["connector_config"]["mir_host_address"] = 123
    with pytest.raises(ValidationError):
        MiR100Config(**broken_config)
    default_user_scripts = deepcopy(example_mir100_configuration_dict)
    default_user_scripts.pop("user_scripts")
    MiR100Config(**default_user_scripts)
