#!/usr/bin/env python
# -*- coding: utf-8 -*-

# MIT License
#
# Copyright (C) 2024 InOrbit, Inc.

# Standard
import html
import json
import threading

# Third Party
from inorbit_edge.commands import COMMAND_MESSAGE
from inorbit_edge.robot import (COMMAND_CUSTOM_COMMAND)
from requests import HTTPError

from inorbit_instock_connector.src.abstract.connector import Connector
from inorbit_instock_connector.src.config import InstockConfig
from inorbit_instock_connector.src.instock.rest import (
    InStockAPIBase, InStockAPIv1, TERMINAL_ORDER_STATUSES
)


class InstockConnector(Connector):
    """InOrbit Connector for the Instock ASRS.

    TODO(russell): Longer description.

    This class handles bi-directional communication with InOrbit and Instock.
    """

    def __init__(self, robot_id: str, config: InstockConfig) -> None:
        """Initialize a new Instock connector.

        TODO(russell): Longer description.

        Args:
            robot_id (str): The ID of the Instock ASRS.
            config (InstockConfig): The configuration for the connector.
        """

        self.config = config
        super().__init__(robot_id, self.config)

        self.current_order_id = None
        self._current_order = None

        # Setup Instock API session
        self.instock_api: InStockAPIBase
        match self.config.connector_config.instock_api_version:
            case "v1":
                self.instock_api = InStockAPIv1(
                    self.config.connector_config.instock_api_url,
                    self.config.connector_config.instock_api_token,
                    self.config.connector_config.instock_org_id,
                    self.config.connector_config.instock_site_id,
                    loglevel=self.config.log_level,
                )
            case _:
                raise ValueError(
                    "Unsupported Instock API version:"
                    + self.config.connector_config.instock_api_version
                )

        # Initialize order and inventory lists.
        # Flags for each list indicate if they have changed and should be
        # published to InOrbit.
        self.orders = {}
        self.orders_changed_flag = False
        self.inventory = []
        self.inventory_changed_flag = False

        # Action handlers
        self.__action_threads = []

    def connect(self) -> None:
        super().connect()

        # Set the initial pose of the ASRS
        self._robot_session.publish_pose(**self.config.connector_config.pose)
        # Set path where to find custom scripts to run
        self._robot_session.register_commands_path(self.user_scripts_dir, r".*\.sh")
        # Create our command callback
        self._robot_session.register_command_callback(self._inorbit_command_handler)

    def disconnect(self) -> None:
        # Wait for actions to finish
        [thread.join() for thread in self.__action_threads]
        self.__action_threads = []
        super().disconnect()

    def execution_loop(self):
        # TODO(russell): have an execution and polling loop that are separate
        # Update and publish orders
        self.get_new_orders()
        self.update_current_orders_statuses()
        self.publish_orders()
        self.publish_current_order()
        self.orders_changed_flag = False  # Reset flag

        # Update and publish inventory
        self.refresh_inventory()
        self.publish_inventory()
        self.inventory_changed_flag = False  # Reset flag

    def _inorbit_command_handler(self, command_name: str, args: list, options: dict):
        """Handle InOrbit commands.

        For now, this connector only allows "message" commands. All others will be
        ignored. Each will be run in its own thread to prevent blocking calls.

        Args:
            command_name (str): The name of the command.
            args (list): The arguments for the command.
            options (dict): The options for the command with result/update functions.
                            See the edge-sdk-python documentation for more information.
        """

        if command_name == COMMAND_CUSTOM_COMMAND:
            self._logger.info(f"Received '{command_name}'!. {args}")
            # The Edge SDK handles execution
        elif command_name == COMMAND_MESSAGE:
            thread = threading.Thread(
                target=self._handle_message_action, args=(args, options)
            )
            self.__action_threads.append(thread)
            thread.start()
        else:
            self._logger.error(
                f"Instock connector does not support action {command_name}"
            )
            options["result_function"](2)

    def _handle_message_action(self, args: list, options: dict):
        """Handles a message action

        Handles a message action by checking the data and creating an order in Instock.
        This should be called in its own thread.

        Args:
            args (list): A list contain exactly one item containing the message data.
            options (dict): The options for the command with result/update functions.
                            See the edge-sdk-python documentation for more information.
        """
        # Check the data
        if len(args) != 1:
            self._logger.error("'args' must contain exactly one item.")
            options["result_function"](2)
            return

        # Check if the message was escaped
        message = html.unescape(args[0])

        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            self._logger.error("Could not decode string into JSON.")
            options["result_function"](2)
            return

        self._logger.debug(f"Received message: {data}")

        if not isinstance(data, dict):
            self._logger.error("Base JSON data must be a dict.")
            options["result_function"](2)
            return

        if not all(key in ["lines", "order_id"] for key in
                   data.keys()) or "lines" not in data.keys():
            self._logger.error(
                'Base object must only contain the keys "lines" and "order_id" with '
                '"lines" being mandatory.'
            )
            options["result_function"](2)
            return

        lines = data["lines"]
        order_id = data.get("order_id")

        if not isinstance(lines, list):
            self._logger.error('"lines" must be a list.')
            options["result_function"](2)
            return

        for line in lines:
            if not isinstance(line, dict):
                self._logger.error("Each article must be an object.")
                options["result_function"](2)
                return
            if set(line.keys()) != {"article_id", "qty"}:
                self._logger.error(
                    'Articles must only contain the keys "article_id" and "qty".'
                )
                options["result_function"](2)
                return
            if not isinstance(line["article_id"], str):
                self._logger.error('The value for "article_id" must be a string.')
                options["result_function"](2)
                return
            if not isinstance(line["qty"], int):
                self._logger.error('The value for "qty" must be an integer.')
                options["result_function"](2)
                return

        if "order_id" in data and not isinstance(order_id, str):
            self._logger.error('"order_id" must be a string if provided.')
            options["result_function"](2)
            return

        if order := self.instock_api.create_order(lines, order_id):
            self._logger.info(f"Order created: {order}")

            # Save ID as the last ID
            # If the ID is not provided, it gets created by instock_api.create_order()
            if order.get("order_id"):
                self.current_order_id = order.get("order_id")

            options["result_function"](0)
        else:
            self._logger.error(f"Order creation action failed: {data}")
            options["result_function"](2)

    def update_current_orders_statuses(self):
        """Update the status of the current orders"""
        # TODO: Don't iterate over all orders every time.
        # Set a maximum number of orders/ max age of orders to keep track of.
        to_remove_ids = []  # To be removed later

        for order_id, order in self.orders.items():
            order_status = order.get("order_status")

            # Only update the status if the order is not done or canceled
            if order_id and order_status not in TERMINAL_ORDER_STATUSES:
                self.get_logger().debug(
                    f'Querying status of "{order_status}" order {order_id}'
                )
                try:
                    new_status = self.instock_api.get_order_status(order_id)[
                        "order_status"
                    ]
                except Exception as e:
                    self.get_logger().error(
                        f"Failed to get status of order {order_id}: {e}"
                    )
                    # TODO(russell): We need a better cleanup policy (see TODO above)
                    to_remove_ids.append(order_id)  # Flag the order for removal
                    continue

                # Update the status
                if new_status != order_status:
                    self.get_logger().debug(
                        f'Got new status "{new_status}" '
                        f"for order {order_id}: {new_status}"
                    )
                    self.orders[order_id]["order_status"] = new_status
                    self.orders_changed_flag = True

        # Removed orders flagged for remove
        [self.orders.pop(key) for key in to_remove_ids]

    def get_new_orders(self):
        """Get new orders from Instock."""
        # Get orders after the last order in the list
        try:
            # TODO(russell): make this configurable
            # Get the last 10 orders
            current_orders = self.instock_api.get_orders()[-10:]

            if current_orders:
                # For change control
                updated = False
                original_orders = self.orders.copy()

                # Convert Instock array to a dictionary based on order_id keys
                current_orders_dict = {
                    order["order_id"]: order for order in current_orders
                }

                # Check if any keys are no longer in the last 10
                orders_missing_from_current = list(
                    set(self.orders.keys()) - set(current_orders_dict.keys())
                )
                if orders_missing_from_current:
                    updated = True
                    [self.orders.pop(key) for key in orders_missing_from_current]

                # Update values
                self.orders.update(current_orders_dict)
                if original_orders != self.orders:
                    self.get_logger().debug("Orders updated from Instock")
                    updated = True

                self.orders_changed_flag = updated
        except Exception as e:
            self.get_logger().error(f"Failed to get new orders: {e}")

    def publish_current_order(self):
        """Publish the status of the current order."""
        if not self.current_order_id:
            return

        try:
            order = self.instock_api.get_order_status(self.current_order_id)
        except HTTPError as e:
            self._logger.debug(e.response.json())
            self._logger.error(f"Could not retrieve order '{self.current_order_id}'")
            order = None

        # TODO(russell): Publish at a set rate to be resilient to network drops
        # Check for a change
        if (
            self._current_order is None
            or order is None
            or self._current_order["order_id"] != order["order_id"]
            or self._current_order["order_status"] != order["order_status"]
        ):
            self._logger.debug(
                f"Update found for current order {self.current_order_id}"
            )
            self._current_order = order
            # TODO(russell): Gather all key/values and publish at a set rate
            self.get_robot_session().publish_key_values({
                "current_order": order,
            })

    def publish_orders(self):
        """Publish the last 10 of orders to InOrbit if they have been updated."""
        if not self.orders_changed_flag:
            return
        self.get_logger().debug("Publishing updated order list")

        self.get_robot_session().publish_key_values(
            {
                "orders": self.orders,
            }
        )

    def refresh_inventory(self):
        """Refresh the inventory list from the API."""
        try:
            inventory = self.instock_api.get_inventory()
            self.inventory_changed_flag = self.inventory != inventory
            if self.inventory_changed_flag:
                self.get_logger().debug("Received inventory update")
                self.inventory = inventory
        except Exception as e:
            self.get_logger().error(f"Failed to get inventory: {e}")

    def publish_inventory(self):
        """Publish the inventory list to InOrbit if it has been updated."""
        if not self.inventory_changed_flag:
            return
        self.get_logger().debug("Publishing inventory list")
        self.get_robot_session().publish_key_values(
            {
                "inventory": self.inventory,
            }
        )
