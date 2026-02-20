# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest
from inorbit_connector.connector import CommandFailure
from inorbit_omron_connector.src.commands import parse_custom_command_args

def test_parse_custom_command_args_dict():
    """Test parsing with dictionary arguments."""
    args = ["myScript", {"param1": "value1", "param2": 123}]
    name, params = parse_custom_command_args(args)
    assert name == "myScript"
    assert params == {"param1": "value1", "param2": 123}

def test_parse_custom_command_args_list():
    """Test parsing with list arguments (flat key-value pairs)."""
    args = ["myScript", ["param1", "value1", "param2", "123"]]
    name, params = parse_custom_command_args(args)
    assert name == "myScript"
    # Note: keys become strings, values are preserved as-is from the list items
    assert params == {"param1": "value1", "param2": "123"}

def test_parse_custom_command_args_list_odd_length():
    """Test parsing with list arguments of odd length (invalid)."""
    args = ["myScript", ["param1", "value1", "param2"]]
    with pytest.raises(CommandFailure) as excinfo:
        parse_custom_command_args(args)
    assert "Expected even number of arguments" in str(excinfo.value.stderr)

def test_parse_custom_command_args_empty():
    """Test parsing empty arguments."""
    with pytest.raises(CommandFailure) as excinfo:
        parse_custom_command_args([])
    assert "Custom command arguments cannot be empty" in str(excinfo.value.stderr)

def test_parse_custom_command_args_only_name():
    """Test parsing with only script name."""
    args = ["myScript"]
    name, params = parse_custom_command_args(args)
    assert name == "myScript"
    assert params == {}
