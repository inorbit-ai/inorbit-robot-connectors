#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import pytest
import yaml

from inorbit_instock_connector.src.config.utils import read_yaml, write_yaml
from unittest.mock import mock_open, patch


@patch("builtins.open", new_callable=mock_open, read_data="test: val")
def test_read_yaml_no_robot_id(mock_file):
    file_path = "/dummy/path.yaml"
    expected_result = {"test": "val"}
    result = read_yaml(file_path)
    assert result == expected_result


@patch("builtins.open", new_callable=mock_open, read_data="test: val")
def test_read_yaml_with_robot_id(mock_file):
    file_path = "/dummy/path.yaml"
    robot_id = "test"
    expected_result = "val"
    result = read_yaml(file_path, robot_id)
    assert result == expected_result


@patch("builtins.open", new_callable=mock_open, read_data="test: val")
def test_read_yaml_with_invalid_robot_id(mock_file):
    file_path = "/dummy/path.yaml"
    robot_id = "invalid"

    with pytest.raises(IndexError):
        read_yaml(file_path, robot_id)


@patch("builtins.open", new_callable=mock_open, read_data="")
def test_read_yaml_empty_file(mock_file):
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


def test_write_yaml():
    test_file = "test.yaml"
    test_data = {"key": "value"}

    # Ensure the test file doesn't exist before the test
    if os.path.exists(test_file):
        os.remove(test_file)

    # Run the function with the test data
    write_yaml(test_file, test_data)

    # Ensure the file was created
    assert os.path.exists(test_file)

    # Check the content of the file
    with open(test_file) as file:
        content = yaml.load(file, Loader=yaml.FullLoader)
    assert content == test_data

    # Cleanup: Remove the test file
    os.remove(test_file)


def test_write_yaml_empty_data():
    test_file = "test_empty.yaml"
    test_data = {}

    # Ensure the test file doesn't exist before the test
    if os.path.exists(test_file):
        os.remove(test_file)

    # Run the function with the test data
    write_yaml(test_file, test_data)

    # Ensure the file was created
    assert os.path.exists(test_file)

    # Check the content of the file
    with open(test_file) as file:
        content = yaml.load(file, Loader=yaml.FullLoader)
    assert content == test_data

    # Cleanup: Remove the test file
    os.remove(test_file)
