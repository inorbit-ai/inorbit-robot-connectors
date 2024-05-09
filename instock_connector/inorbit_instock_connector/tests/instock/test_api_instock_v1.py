#!/usr/bin/env python
# -*- coding: utf-8 -*-

# MIT License
#
# Copyright (C) 2024 InOrbit, Inc.

# Standard
import builtins
from datetime import datetime

# Third Party
import pytest
import requests_mock as req_mock
from requests.exceptions import HTTPError

from inorbit_instock_connector.src.instock.rest import InStockAPIv1

ORG_ID = "org_id"
SITE_ID = "site_id"
BASE_URL = "http://example.com"
TOKEN = "token"


def create_instock_api_v1(
    base_url=BASE_URL,
    api_token=TOKEN,
    org_id=ORG_ID,
    site_id=SITE_ID,
):
    """Create an instance of the InStockAPIv1 class."""
    api = InStockAPIv1(
        base_url=base_url,
        api_token=api_token,
        org_id=org_id,
        site_id=site_id,
    )
    return api


@pytest.fixture(autouse=True)
def disable_network_calls(monkeypatch, requests_mock):
    # Including requests_mock will disable network calls on every test
    pass


@pytest.fixture(autouse=True)
def disable_open(monkeypatch):
    _original_open = builtins.open

    def patched_open(*args, **kwargs):
        raise Exception("File system access disabled")

    builtins.open = patched_open
    yield
    builtins.open = _original_open


@pytest.fixture
def instock_api_v1(monkeypatch, requests_mock):
    """Initialize an InStockAPIv1 instance patching pickle.load() and pickle.dump()."""

    requests_mock.get(f"{BASE_URL}/sites")
    monkeypatch.setattr(InStockAPIv1, "_load_order_cache", lambda x: None)
    monkeypatch.setattr(InStockAPIv1, "_store_order_cache", lambda x: None)
    api = create_instock_api_v1()
    return api


def datetime_valid(dt_str):
    """Test dt_str is a valid ISO datetime string."""
    try:
        datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


# TODO(russell): See comment in __init__
# def test_initialize(requests_mock, monkeypatch):
#     # Test it tries to authenticate with the API
#     adapter = requests_mock.get(f"{BASE_URL}/sites")
#     monkeypatch.setattr(InStockAPIv1, "_load_order_cache", lambda x: None)
#     monkeypatch.setattr(InStockAPIv1, "_store_order_cache", lambda x: None)
#     create_instock_api_v1()
#     assert adapter.called
#     assert adapter.last_request.headers["Authorization"] == f"Bearer {TOKEN}"
#     # Test it raises value error if authentication fails
#     adapter = requests_mock.get(f"{BASE_URL}/sites", status_code=401)
#     with pytest.raises(ValueError):
#         create_instock_api_v1()


def test_paginated_data_request(instock_api_v1, requests_mock):
    test_pages = [
        {
            "has_more": True,
            "next_cursor": "cursor1",
            "data": [{"id": 1}],
        },
        {
            "has_more": True,
            "next_cursor": "cursor1",
            "data": [{"id": 2}],
        },
        {
            "has_more": False,
            "next_cursor": "",
            "data": [{"id": 3}],
        },
    ]
    # Test it yields the correct data
    page_size = 17
    url = f"{BASE_URL}/pages"

    expected_cursor = ""

    def match_query(request):
        return (
            request.url.split("?")[0] == url
            and request.qs.get("pagesize") == [str(page_size)]
            and request.qs.get("start_cursor")
            == ([expected_cursor] if expected_cursor else None)
        )

    adapter = requests_mock.get(
        req_mock.ANY, json=test_pages[0], additional_matcher=match_query
    )
    i = 0
    for i, (page, next_cursor) in enumerate(
        instock_api_v1._paginated_data_request(url=url, page_size=page_size)
    ):
        assert adapter.called
        assert page == test_pages[i]
        assert next_cursor == test_pages[i]["next_cursor"]

        expected_cursor = test_pages[i]["next_cursor"]
        i += 1
        adapter.reset()
        if i < 3:
            adapter = requests_mock.get(
                req_mock.ANY, json=test_pages[i], additional_matcher=match_query
            )
    assert i == len(test_pages)

    # Returns data even if no `next_cursor` or `has_more` is found
    url = f"{BASE_URL}/sites"
    data = {"data": [{"id": 1}]}
    requests_mock.get(url, json=data)
    response, cursor = instock_api_v1._paginated_data_request(url=url).__next__()
    assert response == data
    assert cursor is None


def test_create_order(requests_mock, instock_api_v1):
    adapter = requests_mock.post(
        f"{BASE_URL}/{SITE_ID}/orders", json={"Hello": "World"}
    )
    request = [{"article_id": "123", "qty": 2}, {"article_id": "234", "qty": 5}]
    returned_value = instock_api_v1.create_order(lines=request, order_id="orbito")
    assert returned_value

    # Assert the response
    body = adapter.last_request.json()
    assert body["org_id"] == ORG_ID
    assert body["site_id"] == SITE_ID
    assert type(body["order_id"]) is str
    assert body["order_id"] == "orbito"
    assert body["kind"] == "customer"
    assert datetime_valid(body["placed_at"])
    assert len(body["lines"]) == 2
    for i, line in enumerate(body["lines"]):
        assert line["article_id"] == request[i]["article_id"]
        assert line["qty"] == request[i]["qty"]
        assert type(line["line_id"]) is str
    assert returned_value == body

    # Test failed request
    adapter = requests_mock.post(
        f"{BASE_URL}/{SITE_ID}/orders", status_code=500
    )
    assert instock_api_v1.create_order(lines=request, order_id="orbito") is None


def test_get_order_status(requests_mock, instock_api_v1):
    # Test it returns the order status
    order_id = "123"
    status = {
        "org_id": ORG_ID,
        "site_id": SITE_ID,
        "order_id": order_id,
        "order_status": "canceled",  # A terminal status
        "timestamp": "2024-04-19T23:38:10Z",
        "ordertask_ids": [],
        "lines": [
            {
                "line_id": "inorbit-534bf716-1c55-4791-a64f-a6363ab1db96",
                "article_id": "043000200261",
                "qty": {"reserved": 0, "free": 0, "requested": 1},
            },
            {
                "line_id": "inorbit-ac8cefda-db47-4eb7-a053-b5c87370e96a",
                "article_id": "076808516135",
                "qty": {"reserved": 1, "free": 999, "requested": 2},
            },
        ],
    }
    adapter = requests_mock.get(
        f"{BASE_URL}/{SITE_ID}/orders/{order_id}/status", json=status
    )
    assert instock_api_v1.get_order_status(order_id) == status
    assert adapter.called

    # Test it caches terminal statuses and doesn't cache non-terminal statuses
    order_id = "124"
    status |= {"order_id": order_id}
    adapter = requests_mock.get(
        f"{BASE_URL}/{SITE_ID}/orders/{order_id}/status", json=status
    )
    assert instock_api_v1.get_order_status(order_id) == status
    assert instock_api_v1.get_order_status(order_id) == status
    assert adapter.called_once, "The status should be cached"

    # Test it doesn't cache non-terminal statuses
    order_id = "125"
    status |= {
        "order_status": "processing",
        "order_id": order_id,
    }  # A non terminal status
    adapter = requests_mock.get(
        f"{BASE_URL}/{SITE_ID}/orders/{order_id}/status", json=status
    )
    assert instock_api_v1.get_order_status(order_id) == status
    assert instock_api_v1.get_order_status(order_id) == status
    assert adapter.call_count == 2, "The status should not be cached"

    # Test it handles not founds
    order_id = "126"
    adapter = requests_mock.get(
        f"{BASE_URL}/{SITE_ID}/orders/{order_id}/status", status_code=404
    )
    assert instock_api_v1.get_order_status(order_id) is None

    # Test it doesn't handle other errors
    order_id = "127"
    adapter = requests_mock.get(
        f"{BASE_URL}/{SITE_ID}/orders/{order_id}/status", status_code=500
    )
    with pytest.raises(HTTPError):
        instock_api_v1.get_order_status(order_id)


def test_refresh_and_get_orders(instock_api_v1, requests_mock):
    order_pages = [
        {
            "has_more": True,
            "next_cursor": "1",
            "orders": [
                {
                    "org_id": ORG_ID,
                    "site_id": SITE_ID,
                    "order_id": "16ae37cb-c6e2-4002-93d1-ba6480d7e993",
                    "kind": "reception",
                    "placed_at": "2024-04-18T22:00:01Z",
                    "attributes": {},
                    "lines": [
                        {
                            "line_id": "9df7f2e5-99b4-416d-aa8c-3a957f8679d5",
                            "article_id": "302.3",
                            "qty": 1,
                        },
                        {
                            "line_id": "dccbe489-225c-4ee2-b503-2dc85197dea0",
                            "article_id": "302.3",
                            "qty": 1,
                        },
                    ],
                },
                {
                    "org_id": ORG_ID,
                    "site_id": SITE_ID,
                    "order_id": "bb461b60-ccbc-4827-aeea-224facdfdf42",
                    "kind": "extraction",
                    "placed_at": "2024-04-18T22:12:20Z",
                    "attributes": {},
                    "lines": [
                        {
                            "line_id": "d32e977f-71e3-4b0f-ac20-e0e8b17df7db",
                            "article_id": "302.3",
                            "qty": 1,
                        }
                    ],
                },
                {
                    "org_id": ORG_ID,
                    "site_id": SITE_ID,
                    "order_id": "51.35.3-B:eie:inorbitusa:6e6ebdb2\
                            -92d5-476e-8ccd-f900a1afeb47",
                    "kind": "adjustment",
                    "placed_at": "2024-04-18T22:14:21Z",
                    "attributes": {},
                    "lines": [
                        {
                            "line_id": "51.35.3-B:eie:inorbitusa:6e6ebdb2\
                                    -92d5-476e-8ccd-f900a1afeb47:0",
                            "article_id": "302.3",
                            "qty": 1,
                        }
                    ],
                },
            ],
            "org_id": ORG_ID,
            "site_id": SITE_ID,
        },
        {
            "has_more": False,
            "next_cursor": "",
            "orders": [
                {
                    "org_id": ORG_ID,
                    "site_id": SITE_ID,
                    "order_id": "520e3f1c-5784-45d6-8eb4-a899c473a0eb",
                    "kind": "customer",
                    "placed_at": "2024-04-18T22:26:40Z",
                    "attributes": {},
                    "lines": [
                        {
                            "line_id": "d4895195-de70-47aa-b289-d9328f3c09e3",
                            "article_id": "R1S1B1-H20Bottle",
                            "qty": 3,
                        }
                    ],
                },
                {
                    "org_id": ORG_ID,
                    "site_id": SITE_ID,
                    "order_id": "8e6ae771-f454-4f1d-bf96-d2a3d438d2d3",
                    "kind": "customer",
                    "placed_at": "2024-04-18T22:36:08Z",
                    "attributes": {},
                    "lines": [
                        {
                            "line_id": "ce6631d9-0146-49bd-a182-b8678e10ead8",
                            "article_id": "R1S1B1-H20Bottle",
                            "qty": 3,
                        }
                    ],
                },
            ],
            "org_id": ORG_ID,
            "site_id": SITE_ID,
        },
    ]

    orders_list = [order for page in order_pages for order in page["orders"]]

    instock_api_v1._order_page_size = len(order_pages[0]["orders"])

    def get_response(request, context):
        cursor = request.qs.get("start_cursor")
        if cursor is None:
            cursor = [0]
        if cursor[0] == "invalid":
            return {}
        return order_pages[int(cursor[0])]

    # Test it returns the correct orders
    url = f"{BASE_URL}/{SITE_ID}/orders"
    adapter = requests_mock.get(
        req_mock.ANY,
        json=get_response,
        additional_matcher=lambda x: x.url.split("?")[0] == url,
    )
    assert instock_api_v1.get_orders() == orders_list
    assert adapter.call_count == len(order_pages)

    # Test it caches the orders and only fetches the last page
    adapter.reset()
    assert instock_api_v1.get_orders() == orders_list
    assert adapter.call_count == 1

    # Test it gets new orders from last page
    adapter.reset()
    new_order = {
        "org_id": ORG_ID,
        "site_id": SITE_ID,
        "order_id": "inorbit-07c501b7-a9e6-4321-a2c2-e00bc9db80c4",
        "kind": "customer",
        "placed_at": "2024-04-19T22:31:27Z",
        "attributes": {},
        "lines": [
            {
                "line_id": "inorbit-1ea5dcc6-e0dc-4aa1-ac97-800c3070ffa7",
                "article_id": "076808516135",
                "qty": 1,
            }
        ],
    }
    order_pages[1]["orders"].append(new_order)
    orders_list.append(new_order)
    assert instock_api_v1.get_orders() == orders_list
    assert adapter.call_count == 1

    # Test it fetches from the beginning if the cursor is invalid
    adapter.reset()
    instock_api_v1._last_order_cursor = "invalid"
    assert instock_api_v1.get_orders() == orders_list

    # One with the invalid cursor and two for all from the beginning
    assert (
        adapter.call_count == 3
    )

    # Test it returns fails if the request is not valid, but also clears the cache
    adapter = requests_mock.get(
        req_mock.ANY,
        additional_matcher=lambda x: x.url.split("?")[0] == url,
        status_code=404,
    )
    with pytest.raises(HTTPError):
        instock_api_v1.get_orders()
    assert adapter.call_count == 1
    # It cleared the cache
    adapter = requests_mock.get(
        req_mock.ANY,
        json=get_response,
        additional_matcher=lambda x: x.url.split("?")[0] == url,
    )
    assert instock_api_v1.get_orders() == orders_list
    assert adapter.call_count == 2

    # Test it returns None if after_id isn't found
    adapter.reset()
    assert instock_api_v1.get_orders(after_id="invalid") is None
    # Test it returns the correct list if after_id is valid
    assert (
        instock_api_v1.get_orders(after_id=orders_list[0]["order_id"])
        == orders_list[1:]
    )


def test_get_inventory(requests_mock, instock_api_v1):
    inventory_pages = [
        {
            "has_more": True,
            "next_cursor": "1",
            "org_id": ORG_ID,
            "site_id": SITE_ID,
            "timestamp": "2024-04-20T05:27:46Z",
            "articles": [
                {
                    "article_id": "1",
                    "qty": {"reserved": 18, "free": 982, "registered": 0},
                },
                {
                    "article_id": "2",
                    "qty": {"reserved": 18, "free": 982, "registered": 0},
                },
                {
                    "article_id": "3",
                    "qty": {"reserved": 18, "free": 982, "registered": 0},
                },
            ],
        },
        {
            "has_more": False,
            "next_cursor": "",
            "org_id": ORG_ID,
            "site_id": SITE_ID,
            "timestamp": "2024-04-20T05:27:46Z",
            "articles": [
                {
                    "article_id": "4",
                    "qty": {"reserved": 18, "free": 982, "registered": 0},
                },
                {
                    "article_id": "5",
                    "qty": {"reserved": 18, "free": 982, "registered": 0},
                },
                {
                    "article_id": "6",
                    "qty": {"reserved": 18, "free": 982, "registered": 0},
                },
            ],
        },
    ]
    inventory_list = [
        article for page in inventory_pages for article in page["articles"]
    ]

    url = f"{BASE_URL}/{SITE_ID}/inventory"

    def get_response(request, context):
        cursor = request.qs.get("start_cursor", [0])[0]
        return inventory_pages[int(cursor)]

    adapter = requests_mock.get(
        req_mock.ANY,
        json=get_response,
        additional_matcher=lambda x: x.url.split("?")[0] == url,
    )

    # Test it returns the correct inventory
    assert instock_api_v1.get_inventory() == inventory_list
    assert adapter.call_count == len(inventory_pages)
