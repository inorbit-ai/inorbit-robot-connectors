#!/usr/bin/env python
# -*- coding: utf-8 -*-

# MIT License
#
# Copyright (C) 2024 InOrbit, Inc.


from unittest.mock import mock_open, patch

import pytest
import yaml

from inorbit_instock_connector.src.abstract.utils import read_yaml


@patch("builtins.open", new_callable=mock_open, read_data="test: val")
def test_read_yaml_no_robot_id(_):
    file_path = "/dummy/path.yaml"
    expected_result = {"test": "val"}
    result = read_yaml(file_path)
    assert result == expected_result


@patch("builtins.open", new_callable=mock_open, read_data="test: val")
def test_read_yaml_with_robot_id(_):
    file_path = "/dummy/path.yaml"
    robot_id = "test"
    expected_result = "val"
    result = read_yaml(file_path, robot_id)
    assert result == expected_result


@patch("builtins.open", new_callable=mock_open, read_data="test: val")
def test_read_yaml_with_invalid_robot_id(_):
    file_path = "/dummy/path.yaml"
    robot_id = "invalid"

    with pytest.raises(IndexError):
        read_yaml(file_path, robot_id)


@patch("builtins.open", new_callable=mock_open, read_data="")
def test_read_yaml_empty_file(_):
    file_path = "/dummy/path.yaml"
    expected_result = {}
    result = read_yaml(file_path)
    assert result == expected_result


@patch("builtins.open", create=True)
def test_read_yaml_file_not_found(mock_file):
    file_path = "/dummy/path.yaml"
    mock_file.side_effect = FileNotFoundError()
    with pytest.raises(FileNotFoundError):
        read_yaml(file_path)


@patch("builtins.open", new_callable=mock_open, read_data="{test: val")
def test_read_yaml_invalid_yaml(mock_file):
    file_path = "/dummy/path.yaml"
    with pytest.raises(yaml.YAMLError):
        read_yaml(file_path)
