# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Tests for `gausium_open_platform_connector.src.api.data_poller`."""

from __future__ import annotations

from unittest.mock import AsyncMock, call

import pytest

from gausium_open_platform_connector.src.api.data_poller import (
    ROBOTS_PAGE_SIZE,
    DataPoller,
)

SN_1 = "GS000-0000-000-0001"
SN_2 = "GS000-0000-000-0002"


@pytest.fixture()
def client() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def poller(client: AsyncMock) -> DataPoller:
    return DataPoller(client, [SN_1, SN_2])


@pytest.mark.asyncio
async def test_poll_status_fans_out_per_robot(client: AsyncMock, poller: DataPoller) -> None:
    client.batch_status_v1.return_value = {
        SN_1: {"taskState": "IDLE"},
        SN_2: {"taskState": "RUNNING"},
    }
    client.batch_status_v2.return_value = {SN_1: {"cleanModes": []}}

    await poller.poll_status_once()

    client.batch_status_v1.assert_awaited_once_with([SN_1, SN_2])
    client.batch_status_v2.assert_awaited_once_with([SN_1, SN_2])
    assert poller.get_state(SN_1).status == {"taskState": "IDLE"}
    assert poller.get_state(SN_1).status_v2 == {"cleanModes": []}
    assert poller.get_state(SN_2).status == {"taskState": "RUNNING"}
    # SN_2 absent from the v2 response keeps its (empty) cache
    assert poller.get_state(SN_2).status_v2 == {}
    assert poller.get_state(SN_1).api_connected is True
    assert poller.get_state(SN_2).api_connected is True


@pytest.mark.asyncio
async def test_poll_status_failure_keeps_cache(client: AsyncMock, poller: DataPoller) -> None:
    client.batch_status_v1.return_value = {SN_1: {"taskState": "IDLE"}}
    client.batch_status_v2.return_value = {SN_1: {"cleanModes": []}}
    await poller.poll_status_once()

    client.batch_status_v1.return_value = None
    client.batch_status_v2.return_value = None
    await poller.poll_status_once()

    assert poller.get_state(SN_1).status == {"taskState": "IDLE"}
    assert poller.get_state(SN_1).status_v2 == {"cleanModes": []}
    assert poller.get_state(SN_1).api_connected is False
    assert poller.get_state(SN_2).api_connected is False


@pytest.mark.asyncio
async def test_poll_status_partial_failure(client: AsyncMock, poller: DataPoller) -> None:
    client.batch_status_v1.return_value = None
    client.batch_status_v2.return_value = {SN_1: {"cleanModes": []}}

    await poller.poll_status_once()

    assert poller.get_state(SN_1).status == {}
    assert poller.get_state(SN_1).status_v2 == {"cleanModes": []}
    # At least one batch call succeeded, so the API is reachable
    assert poller.get_state(SN_1).api_connected is True


@pytest.mark.asyncio
async def test_poll_status_ignores_unknown_serial_numbers(
    client: AsyncMock, poller: DataPoller
) -> None:
    client.batch_status_v1.return_value = {"GS999-9999-999-9999": {"taskState": "IDLE"}}
    client.batch_status_v2.return_value = {}

    await poller.poll_status_once()

    assert poller.get_state(SN_1).status == {}


@pytest.mark.asyncio
async def test_poll_robot_data_stops_on_short_page(client: AsyncMock, poller: DataPoller) -> None:
    client.get_robots.return_value = {
        "robots": [
            {"serialNumber": SN_1, "displayName": "Target1534"},
            {"serialNumber": "GS999-9999-999-9999", "displayName": "Other"},
        ]
    }

    await poller.poll_robot_data_once()

    client.get_robots.assert_awaited_once_with(page=1, page_size=ROBOTS_PAGE_SIZE)
    assert poller.get_state(SN_1).robot_data == {
        "serialNumber": SN_1,
        "displayName": "Target1534",
    }
    assert poller.get_state(SN_2).robot_data == {}


@pytest.mark.asyncio
async def test_poll_robot_data_pages_until_all_seen(client: AsyncMock, poller: DataPoller) -> None:
    full_page = [
        {"serialNumber": f"GS999-0000-000-{i:04d}"} for i in range(ROBOTS_PAGE_SIZE - 1)
    ] + [{"serialNumber": SN_1, "displayName": "Target1534"}]
    second_page = [{"serialNumber": SN_2, "displayName": "Target1102"}] + [
        {"serialNumber": f"GS998-0000-000-{i:04d}"} for i in range(ROBOTS_PAGE_SIZE - 1)
    ]
    client.get_robots.side_effect = [{"robots": full_page}, {"robots": second_page}]

    await poller.poll_robot_data_once()

    assert client.get_robots.await_args_list == [
        call(page=1, page_size=ROBOTS_PAGE_SIZE),
        call(page=2, page_size=ROBOTS_PAGE_SIZE),
    ]
    assert poller.get_state(SN_1).robot_data["displayName"] == "Target1534"
    assert poller.get_state(SN_2).robot_data["displayName"] == "Target1102"


@pytest.mark.asyncio
async def test_poll_robot_data_failure_keeps_cache(client: AsyncMock, poller: DataPoller) -> None:
    client.get_robots.side_effect = [
        {"robots": [{"serialNumber": SN_1, "displayName": "Target1534"}]},
        None,
    ]
    await poller.poll_robot_data_once()

    await poller.poll_robot_data_once()

    assert poller.get_state(SN_1).robot_data["displayName"] == "Target1534"
