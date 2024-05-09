#!/usr/bin/env python
# -*- coding: utf-8 -*-

# MIT License
#
# Copyright (C) 2024 InOrbit, Inc.

# Standard
import logging
import pickle
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

# Third Party
from requests import Session, Response
from requests.exceptions import HTTPError

from inorbit_instock_connector.src.abstract import LogLevels

# TODO(tomi): Automatically create folder
LOCAL_ORDER_CACHE_FILE = ".cache/order_cache.pkl"

TERMINAL_ORDER_STATUSES = ["done", "canceled"]


class InStockAPIBase(ABC):
    def __init__(self, loglevel: LogLevels = logging.INFO):
        self.logger = logging.getLogger(name=self.__class__.__name__)
        self.logger.setLevel(loglevel.value)

    def _handle_status(self, res, request_args):
        """Log and raise an exception if the request failed."""
        try:
            res.raise_for_status()
        except HTTPError as e:
            self.logger.error(f"Error making request: {e}\nArguments: {request_args}")
            raise e

    def _get(self, url: str, session: Session, **kwargs) -> Response:
        """Perform a GET request."""
        self.logger.debug(f"GETing {url}: {kwargs}")
        res = session.get(url, **kwargs)
        self._handle_status(res, kwargs)
        return res

    def _post(self, url: str, session: Session, **kwargs) -> Response:
        """Perform a POST request."""
        self.logger.debug(f"POSTing {url}: {kwargs}")
        res = session.post(url, **kwargs)
        self.logger.debug(f"Response: {res}")
        self._handle_status(res, kwargs)
        return res

    def _delete(self, url: str, session: Session, **kwargs) -> Response:
        """Perform a DELETE request."""
        self.logger.debug(f"DELETE {url}: {kwargs}")
        res = session.delete(url, **kwargs)
        self.logger.debug(f"Response: {res}")
        self._handle_status(res, kwargs)
        return res

    def _put(self, url: str, session: Session, **kwargs) -> Response:
        """Perform a PUT request."""
        self.logger.debug(f"PUTing {url}: {kwargs}")
        res = session.put(url, **kwargs)
        self.logger.debug(f"Response: {res}")
        self._handle_status(res, kwargs)
        return res

    @abstractmethod
    def _create_api_session(self) -> Session:
        """Configures a session object to interact with the InStock API."""
        pass

    @abstractmethod
    def create_order(self, request) -> dict | None:
        """Create an order within Instock."""
        pass

    @abstractmethod
    def get_order_status(self, order_id: str) -> dict | None:
        """Query the status of an order and return a full order description."""
        pass

    @abstractmethod
    def get_orders(self, after_id: str = None) -> list[dict]:
        """Return a list of all orders later than `id`, not including order status.
        If `id` is None, return all orders."""
        pass

    @abstractmethod
    def get_inventory(self) -> list[dict]:
        """Return a list of inventory of articles with `qty` greater than zero."""
        pass


class InStockAPIv1(InStockAPIBase):
    def __init__(
        self,
        base_url: str,
        api_token: str,
        org_id: str,
        site_id: str,
        loglevel: LogLevels = LogLevels.INFO,
    ):
        if not all([base_url, api_token, org_id, site_id]):
            raise ValueError("Arguments missing")

        super().__init__(loglevel)

        # API configuration
        self._base_url = base_url
        self._api_token = api_token
        self._org_id = org_id
        self._site_id = site_id
        self._session = self._create_api_session()
        # TODO(russell): This logic needs rethinking as test_auth doesn't actually do
        #                this, any HTTP error causes this to fail. A REST client should
        #                return the corresponding HTTP error in the calls themselves.
        # if not self._test_authentication():
        #     raise ValueError("Authentication failed")

        # Orders
        # The orders API is paginated and all new orders are added to the end of the
        # _order_list list.
        # At startup, the full list is loaded and the _last_order_page is saved as a
        # reference to be able to compare it with new requests and find new orders.
        self._order_page_size = 100
        self._last_order_cursor: Optional[str] = None
        self._last_order_page: dict = {}
        self._order_list: list[dict] = []
        # orderId: {order} mapping of orders that have been completed or cancelled.
        # Used to avoid querying the API for old orders.
        self._terminal_order_statuses: dict = {}
        self._load_order_cache()

    # Override
    def _create_api_session(self) -> Session:
        """Create an Instock API session with the necessary headers."""
        session = Session()
        session.headers.update({"Authorization": f"Bearer {self._api_token}"})
        return session

    def _test_authentication(self) -> bool:
        """Make a request to the Instock API using the current session to test the
        authentication.

        Returns:
            bool: whether the request was successful
        """

        url = f"{self._base_url}/sites"
        try:
            res = self._get(url, self._session)
        except HTTPError as e:
            self.logger.error(f"Authentication failed: {e}")
            return False
        return res.status_code == 200

    def _paginated_data_request(
        self, url: str, page_size: int = None, cursor: str = None
    ):
        """Yield a page from a paginated API request.

        Args:
            url (str): request url
            page_size (int, optional): added as a query parameter. Defaults to None.
                if None, the API default will be used.
            cursor (str, optional): added as a query parameter. Defaults to None.
                If a request is made, it is set to the returned next_cursor.

        Yields:
            tuple[dict, str]: tuple(response json, next_cursor)
        """
        while True:
            # Generate the full url
            params = []
            if page_size:
                params.append(f"pageSize={page_size}")
            if cursor:
                params.append(f"start_cursor={cursor}")
            _url = url + "?" + "&".join(params)

            res = self._get(_url, self._session)
            data = res.json()
            has_more = data.get("has_more")
            # Update the cursor for the next iteration
            cursor = data.get("next_cursor")
            yield data, cursor
            if not (cursor and has_more):
                break

    def create_order(self, lines: list, order_id: str = None) -> dict | None:
        """Create an order within Instock."""
        url = f"{self._base_url}/{self._site_id}/orders"

        if not order_id:
            order_id = f"inorbit-{uuid.uuid4()}"

        data = {
            "org_id": self._org_id,
            "site_id": self._site_id,
            "order_id": order_id,
            "kind": "customer",
            # TODO(russell): load from config
            "placed_at": datetime.now(timezone.utc).isoformat(),
            "attributes": {
            },
            "lines": []
        }

        for line in lines:
            data["lines"].append({
                "line_id": f"inorbit-{uuid.uuid4()}",
                "article_id": line["article_id"],
                "qty": line["qty"],
            })

        try:
            # It would be better to send something like the action ID but the Instock
            # API does not currently return anything useful on a 200 response.
            self._post(url, self._session, json=data)
            # Return the order data if successful
            return data
        except HTTPError:
            # Verbose HTTP error already logged in self._post(), just acknowledge here
            self.logger.error("Order creation failed")
            # Return None if not successful
            return None

    # Override
    def get_order_status(self, order_id: str) -> dict | None:
        """Query the status of an order. The returned data is a full order description.

        Returns None if the order is not found.
        """

        # If the order was cached as terminal, return it.
        terminal_order_status = self._terminal_order_statuses.get(order_id)
        if terminal_order_status:
            self.logger.debug(f"Order {order_id} is terminal. Returning cached status.")
            return terminal_order_status

        url = f"{self._base_url}/{self._site_id}/orders/{order_id}/status"
        try:
            res = self._get(url, self._session)
        except HTTPError as e:
            if e.response.status_code == 404:
                # The order was not found.
                self.logger.warning(f"Order {order_id} not found")
                # If the order was in the orders cache, it means it is corrupted and
                # needs to be reset
                for order in self._order_list:
                    if order["order_id"] == order_id:
                        self._clear_local_order_cache()
                        break
                return None
            else:
                raise e
        json = res.json()

        # If the order is terminal, cache it.
        if json.get("order_status") in TERMINAL_ORDER_STATUSES:
            self._terminal_order_statuses[order_id] = json
            self._store_order_cache()

        return json

    # Override
    def get_orders(self, after_id: str = None) -> list[dict] | None:
        """Return a list of all orders later than `id`, not including order status.
        If `id` is None, return all orders. If `id` is not found, return None"""
        try:
            self._refresh_orders()
        except HTTPError as e:
            self.logger.error(f"Error refreshing orders: {e}")
            self._clear_local_order_cache()
            raise e

        if not after_id:
            return self._order_list

        for order in self._order_list:
            if order["order_id"] == after_id:
                return self._order_list[self._order_list.index(order) + 1:]
        return None

    def _refresh_orders(self) -> None:
        """Refresh the list of orders from the API."""
        orders = []
        # Query the last page of orders using the last cursor, and more pages if there
        # is new ones.
        query_number = 0
        for order_list_page, next_cursor in self._paginated_data_request(
            f"{self._base_url}/{self._site_id}/orders",
            self._order_page_size,
            self._last_order_cursor,
        ):
            # If the page was empty, there is an error.
            if not order_list_page.get("orders"):
                # If this is the first query, and it was started from a cursor, clear
                # the local copy and start over.
                if query_number == 0 and self._last_order_cursor:
                    self.logger.warning(
                        "Error querying orders. Requesting from first page."
                    )
                    self._clear_local_order_cache()
                    return self._refresh_orders()
            # If this is the first query, compare the last list of orders with the new
            # one to find new orders.
            if query_number == 0 and self._last_order_page:
                page_orders = order_list_page.get("orders")
                if len(page_orders) > len(self._last_order_page.get("orders")):
                    new_orders = page_orders[len(self._last_order_page.get("orders")):]
                    orders += new_orders
            # Otherwise, the page is new so all orders can be added
            else:
                orders += order_list_page["orders"]

            # Update the last page and cursor
            self._last_order_page = order_list_page
            if next_cursor:
                self._last_order_cursor = next_cursor
            query_number += 1

        # Update the local cache of orders
        self._order_list += orders
        if orders:
            self._store_order_cache()
        self.logger.debug(f"{query_number} pages of orders queried")
        self.logger.debug(f"{len(self._order_list)} orders are tracked")

    # Override
    def get_inventory(self) -> list[dict]:
        """Return a list of inventory of articles with `qty` greater than zero."""
        inventory = []
        for inventory_page, _ in self._paginated_data_request(
            f"{self._base_url}/{self._site_id}/inventory"
        ):
            inventory += inventory_page.get("articles", [])

        return inventory

    def _load_order_cache(self) -> None:
        """Loads order data from disk to avoid fetching every page on startup."""
        try:
            with open(LOCAL_ORDER_CACHE_FILE, "rb") as f:
                data = pickle.load(f)
                (
                    self._order_list,
                    self._order_page_size,
                    self._last_order_cursor,
                    self._last_order_page,
                    self._terminal_order_statuses,
                ) = data
                self.logger.info("Order cache loaded")
        except FileNotFoundError:
            self.logger.warning("No order cache found")
        except ValueError:
            self.logger.error("Error loading order cache")

    def _store_order_cache(self) -> None:
        """Saves order data to disk to avoid fetching every page on startup."""
        with open(LOCAL_ORDER_CACHE_FILE, "wb+") as f:
            data = [
                self._order_list,
                self._order_page_size,
                self._last_order_cursor,
                self._last_order_page,
                self._terminal_order_statuses,
            ]
            pickle.dump(data, f)
            self.logger.info("Order cache stored")

    def _clear_local_order_cache(self) -> None:
        """Clear the memory and disk order cache"""
        self._order_list = []
        self._last_order_cursor = None
        self._last_order_page = {}
        self._terminal_order_statuses = {}
        self._store_order_cache()
        self.logger.info("Order cache cleared")
