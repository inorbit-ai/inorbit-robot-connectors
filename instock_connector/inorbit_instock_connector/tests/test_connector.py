#!/usr/bin/env python
# -*- coding: utf-8 -*-

import unittest.mock as mock

import pytest

from inorbit_instock_connector.src.instock.config_instock import \
    DEFAULT_INSTOCK_API_VERSION, InstockConfig, InstockConfigModel


class TestInstockConnector:
    @pytest.fixture(autouse=True)
    def setup_method(self, monkeypatch):
        monkeypatch.setenv('INORBIT_API_TOKEN', 'mock_api_token')
        # Needs to be here so setenv is mocked before the import
        from inorbit_instock_connector.src.connector import InstockConnector

        config = InstockConfig(
            connector_type="instock",
            connector_config=InstockConfigModel(
                instock_api_url="https://example.com/",
                instock_api_token="123a",
                instock_api_version=DEFAULT_INSTOCK_API_VERSION,
                instock_site_id="123abc",
                instock_org_id="abc123",
                pose={"x": 0.0, "y": 0.0, "yaw": 0.0},
            )
        )

        self.connector = InstockConnector("robot_id", config)
        self.connector._logger = mock.MagicMock()
        self.connector.instock_api = mock.MagicMock()

    def test_handle_message_action_invalid_args(self):
        options = {"result_function": mock.MagicMock()}
        self.connector._handle_message_action([], options)
        self.connector._logger.error.assert_called_once_with(
            "'args' must contain exactly one item.")
        options["result_function"].assert_called_once_with(2)

    def test_handle_message_action_invalid_json(self):
        options = {"result_function": mock.MagicMock()}
        self.connector._handle_message_action(["{invalid_json}"], options)
        self.connector._logger.error.assert_called_once_with(
            "Could not decode string into JSON.")
        options["result_function"].assert_called_once_with(2)

    def test_handle_message_action_json_not_dict(self):
        options = {"result_function": mock.MagicMock()}
        self.connector._handle_message_action(["[1,2,3]"], options)
        self.connector._logger.error.assert_called_once_with(
            "Base JSON data must be a dict.")
        options["result_function"].assert_called_once_with(2)

    def test_handle_message_action_missing_keys(self):
        options = {"result_function": mock.MagicMock()}
        self.connector._handle_message_action(['{"key": "value"}'], options)
        self.connector._logger.error.assert_called_with(
            'Base object must only contain the keys "lines" and "order_id" with '
            '"lines" being mandatory.'
        )
        options["result_function"].assert_called_with(2)

    def test_handle_message_action_invalid_lines(self):
        options = {"result_function": mock.MagicMock()}
        self.connector._handle_message_action(['{"lines": "invalid"}'], options)
        self.connector._logger.error.assert_called_once_with('"lines" must be a list.')
        options["result_function"].assert_called_once_with(2)

    def test_handle_message_action_invalid_dict_in_lines(self):
        options = {"result_function": mock.MagicMock()}
        self.connector._handle_message_action(['{"lines": [1,2,3]}'], options)
        self.connector._logger.error.assert_called_once_with(
            "Each article must be an object.")
        options["result_function"].assert_called_once_with(2)

    def test_handle_message_action_invalid_article_keys(self):
        options = {"result_function": mock.MagicMock()}
        self.connector._handle_message_action(['{"lines": [{"key": "value"}]}'],
                                              options)
        self.connector._logger.error.assert_called_once_with(
            'Articles must only contain the keys "article_id" and "qty".')
        options["result_function"].assert_called_once_with(2)

    def test_handle_message_action_invalid_article_id(self):
        options = {"result_function": mock.MagicMock()}
        self.connector._handle_message_action(
            ['{"lines": [{"article_id": 123, "qty": 1}]}'], options)
        self.connector._logger.error.assert_called_once_with(
            'The value for "article_id" must be a string.')
        options["result_function"].assert_called_once_with(2)

    def test_handle_message_action_invalid_qty(self):
        options = {"result_function": mock.MagicMock()}
        self.connector._handle_message_action(
            ['{"lines": [{"article_id": "abc", "qty": "invalid"}]}'], options)
        self.connector._logger.error.assert_called_once_with(
            'The value for "qty" must be an integer.')
        options["result_function"].assert_called_once_with(2)

    def test_handle_message_action_invalid_order_id(self):
        options = {"result_function": mock.MagicMock()}
        self.connector._handle_message_action(
            ['{"lines": [{"article_id": "abc", "qty": 1}], "order_id": 123}'],
            options,
        )
        self.connector._logger.error.assert_called_once_with(
            '"order_id" must be a string if provided.')
        options["result_function"].assert_called_once_with(2)

    def test_handle_message_action_successful_order_creation(self):
        options = {"result_function": mock.MagicMock()}
        self.connector.instock_api.create_order.return_value = {"order_id": "order1"}
        self.connector._handle_message_action(
            ['{"lines": [{"article_id": "abc", "qty": 1}]}'], options)
        self.connector._logger.info.assert_called_once_with(
            "Order created: {'order_id': 'order1'}")
        options["result_function"].assert_called_once_with(0)

    def test_handle_message_action_failed_order_creation(self):
        options = {"result_function": mock.MagicMock()}
        self.connector.instock_api.create_order.return_value = None
        self.connector._handle_message_action(
            ['{"lines": [{"article_id": "abc", "qty": 1}]}'], options)
        self.connector._logger.error.assert_called_once_with(
            "Order creation action failed: {'lines': [{'article_id': 'abc', 'qty': 1}]}"
        )
        options["result_function"].assert_called_once_with(2)
