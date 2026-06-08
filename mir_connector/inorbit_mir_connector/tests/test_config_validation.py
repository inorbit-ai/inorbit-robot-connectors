# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

from copy import deepcopy

import pytest
import yaml
from pydantic import ValidationError

from inorbit_mir_connector.config.connector_model import ConnectorConfig, load_config


@pytest.fixture
def example_robot_dict():
    return {
        "robot_id": "mir100-1",
        "mir_model": "MiR100",
        "mir_host_address": "localhost",
        "mir_host_port": 80,
        "mir_use_ssl": False,
        "mir_firmware_version": "v2",
    }


@pytest.fixture
def example_configuration_dict(example_robot_dict):
    return {
        "inorbit_robot_key": "1234567890",
        "location_tz": "America/Los_Angeles",
        "connector_type": "mir",
        "logging": {"log_level": "INFO"},
        "connector_config": {
            "mir_api_version": "v2.0",
            "mir_username": "admin",
            "mir_password": "admin",
        },
        "fleet": [example_robot_dict],
    }


def test_valid_config_passes(example_configuration_dict):
    cfg = ConnectorConfig(**example_configuration_dict)
    assert cfg.connector_type == "mir"
    assert cfg.connector_config.mir_api_version == "v2.0"
    assert cfg.fleet[0].mir_model == "MiR100"
    assert cfg.fleet[0].mir_host_address == "localhost"


def test_invalid_base_field_rejected(example_configuration_dict):
    with pytest.raises(ValidationError):
        ConnectorConfig(**example_configuration_dict | {"location_tz": "La Plata"})


def test_missing_connector_config_fields_rejected(example_configuration_dict):
    broken = deepcopy(example_configuration_dict)
    broken["connector_config"] = {"mir_api_version": "v2.0"}  # no credentials
    with pytest.raises(ValidationError):
        ConnectorConfig(**broken)


def test_missing_robot_fields_rejected(example_configuration_dict):
    broken = deepcopy(example_configuration_dict)
    del broken["fleet"][0]["mir_host_address"]
    with pytest.raises(ValidationError):
        ConnectorConfig(**broken)


def test_wrong_connector_type_rejected(example_configuration_dict):
    # Identity enforcement lives in the framework in v3: connector_type
    # must equal MirConnectorConfig.CONNECTOR_TYPE ("mir").
    with pytest.raises(ValidationError, match="CONNECTOR_TYPE 'mir'"):
        ConnectorConfig(**example_configuration_dict | {"connector_type": "MiR100"})


def test_wrong_api_version_rejected(example_configuration_dict):
    broken = deepcopy(example_configuration_dict)
    broken["connector_config"]["mir_api_version"] = "v1.0"
    with pytest.raises(ValidationError):
        ConnectorConfig(**broken)


def test_unknown_mir_model_rejected(example_configuration_dict):
    broken = deepcopy(example_configuration_dict)
    broken["fleet"][0]["mir_model"] = "MiR9000"
    with pytest.raises(ValidationError, match="mir_model"):
        ConnectorConfig(**broken)


def test_unknown_firmware_version_rejected(example_configuration_dict):
    broken = deepcopy(example_configuration_dict)
    broken["fleet"][0]["mir_firmware_version"] = "v9"
    with pytest.raises(ValidationError, match="firmware version"):
        ConnectorConfig(**broken)


def test_waypoint_mission_required_without_temporary_group(example_configuration_dict):
    broken = deepcopy(example_configuration_dict)
    broken["fleet"][0]["enable_temporary_mission_group"] = False
    with pytest.raises(ValidationError, match="default_waypoint_mission_id"):
        ConnectorConfig(**broken)


def test_bad_field_type_rejected(example_configuration_dict):
    broken = deepcopy(example_configuration_dict)
    broken["fleet"][0]["mir_host_address"] = 123
    with pytest.raises(ValidationError):
        ConnectorConfig(**broken)


def test_empty_fleet_rejected(example_configuration_dict):
    with pytest.raises(ValidationError, match="at least one robot"):
        ConnectorConfig(**example_configuration_dict | {"fleet": []})


def test_duplicate_robot_ids_rejected(example_configuration_dict, example_robot_dict):
    with pytest.raises(ValidationError, match="unique"):
        ConnectorConfig(
            **example_configuration_dict
            | {"fleet": [example_robot_dict, deepcopy(example_robot_dict)]}
        )


def test_env_override(monkeypatch, example_configuration_dict):
    # The framework derives the INORBIT_MIR_ env prefix from CONNECTOR_TYPE;
    # a connector_config field omitted from the YAML resolves from the
    # environment. Secrets are injected this way in production.
    monkeypatch.setenv("INORBIT_MIR_MIR_PASSWORD", "from-env")
    config = deepcopy(example_configuration_dict)
    del config["connector_config"]["mir_password"]
    cfg = ConnectorConfig(**config)
    assert cfg.connector_config.mir_password == "from-env"


def test_load_config_reads_flat_yaml(tmp_path, example_configuration_dict):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.dump(example_configuration_dict))
    cfg = load_config(str(config_file))
    assert [robot.robot_id for robot in cfg.fleet] == ["mir100-1"]
    assert cfg.fleet[0].mir_model == "MiR100"


def test_load_config_multi_robot_fleet(tmp_path, example_configuration_dict, example_robot_dict):
    data = deepcopy(example_configuration_dict)
    second = deepcopy(example_robot_dict)
    second["robot_id"] = "mir250-2"
    second["mir_model"] = "MiR250"
    second["mir_host_address"] = "10.0.0.2"
    second["mir_firmware_version"] = "v3"
    data["fleet"] = [example_robot_dict, second]
    config_file = tmp_path / "fleet.yaml"
    config_file.write_text(yaml.dump(data))
    cfg = load_config(str(config_file))
    assert {r.robot_id for r in cfg.fleet} == {"mir100-1", "mir250-2"}
    # Per-robot selection happens at MirConnector construction via
    # to_singular_config; here we just assert both robots validated.
    assert cfg.to_singular_config("mir250-2").fleet[0].mir_model == "MiR250"
