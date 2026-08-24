# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Tests for `gausium_open_platform_connector.src.api.data_poller`."""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, call

import pytest

from gausium_open_platform_connector.src.api.data_poller import (
    ROBOTS_PAGE_SIZE,
    STATUS_CHUNK_SIZE,
    DataPoller,
)

SN_1 = "GS000-0000-000-0001"
SN_2 = "GS000-0000-000-0002"
# A fleet size that splits into 5 chunks
FLEET = [f"GS000-0000-000-{index:04d}" for index in range(55)]


def echo_status(taskState: str):
    """Batch status side effect answering every requested serial number."""
    return lambda serial_numbers, chunk: {sn: {"taskState": taskState} for sn in serial_numbers}


@pytest.fixture()
def client() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def poller(client: AsyncMock) -> DataPoller:
    return DataPoller(client, [SN_1, SN_2])


def test_api_is_unreachable_until_the_first_successful_poll(poller: DataPoller) -> None:
    # A connector starting against a dead API must report its robots offline on the first
    # tick, not wait out a grace period measured from a success that never happened
    assert poller.api_unreachable_secs == math.inf


@pytest.mark.asyncio
async def test_poll_status_fans_out_per_robot(client: AsyncMock, poller: DataPoller) -> None:
    client.batch_status_v1.return_value = {
        SN_1: {"taskState": "IDLE"},
        SN_2: {"taskState": "RUNNING"},
    }
    client.batch_status_v2.return_value = {SN_1: {"cleanModes": []}}

    await poller.poll_status_v1_once()
    await poller.poll_status_v2_once()

    client.batch_status_v1.assert_awaited_once_with([SN_1, SN_2], chunk=0)
    client.batch_status_v2.assert_awaited_once_with([SN_1, SN_2], chunk=0)
    assert poller.get_state(SN_1).status == {"taskState": "IDLE"}
    assert poller.get_state(SN_1).status_v2 == {"cleanModes": []}
    assert poller.get_state(SN_2).status == {"taskState": "RUNNING"}
    # SN_2 absent from the v2 response keeps its (empty) cache
    assert poller.get_state(SN_2).status_v2 == {}
    assert poller.api_connected is True
    assert poller.api_unreachable_secs == 0.0


@pytest.mark.asyncio
async def test_poll_status_failure_keeps_cache(client: AsyncMock, poller: DataPoller) -> None:
    client.batch_status_v1.return_value = {SN_1: {"taskState": "IDLE"}}
    client.batch_status_v2.return_value = {SN_1: {"cleanModes": []}}
    await poller.poll_status_v1_once()
    await poller.poll_status_v2_once()

    client.batch_status_v1.return_value = None
    client.batch_status_v2.return_value = None
    await poller.poll_status_v1_once()
    await poller.poll_status_v2_once()

    assert poller.get_state(SN_1).status == {"taskState": "IDLE"}
    assert poller.get_state(SN_1).status_v2 == {"cleanModes": []}
    assert poller.api_connected is False
    assert 0.0 < poller.api_unreachable_secs < 1.0


@pytest.mark.asyncio
async def test_poll_status_partial_failure(client: AsyncMock, poller: DataPoller) -> None:
    client.batch_status_v1.return_value = None
    client.batch_status_v2.return_value = {SN_1: {"cleanModes": []}}

    await poller.poll_status_v1_once()
    await poller.poll_status_v2_once()

    assert poller.get_state(SN_1).status == {}
    assert poller.get_state(SN_1).status_v2 == {"cleanModes": []}
    # One endpoint answered: the flag gates fleet-wide online status and commands
    assert poller.api_connected is True


@pytest.mark.asyncio
async def test_poll_status_ignores_unknown_serial_numbers(
    client: AsyncMock, poller: DataPoller
) -> None:
    client.batch_status_v1.return_value = {"GS999-9999-999-9999": {"taskState": "IDLE"}}

    await poller.poll_status_v1_once()

    assert poller.get_state(SN_1).status == {}


@pytest.mark.asyncio
async def test_status_sweep_is_chunked_and_reassembled(client: AsyncMock) -> None:
    poller = DataPoller(client, FLEET)
    client.batch_status_v1.side_effect = echo_status("IDLE")

    await poller.poll_status_v1_once()

    requested = [call.args[0] for call in client.batch_status_v1.await_args_list]
    assert [len(chunk) for chunk in requested] == [11, 11, 11, 11, 11]
    # Every serial number is requested exactly once and every robot gets its row back
    assert [sn for chunk in requested for sn in chunk] == FLEET
    assert all(poller.get_state(sn).status == {"taskState": "IDLE"} for sn in FLEET)


@pytest.mark.asyncio
async def test_one_failed_chunk_only_costs_its_own_robots(client: AsyncMock) -> None:
    poller = DataPoller(client, FLEET)
    client.batch_status_v1.side_effect = echo_status("IDLE")
    await poller.poll_status_v1_once()

    def fail_first_chunk(serial_numbers: list[str], chunk: int) -> dict | None:
        return None if chunk == 0 else echo_status("RUNNING")(serial_numbers, chunk)

    client.batch_status_v1.side_effect = fail_first_chunk
    await poller.poll_status_v1_once()

    # The failed chunk's robots keep their cached data; the rest of the fleet updates
    assert poller.get_state(FLEET[0]).status == {"taskState": "IDLE"}
    assert poller.get_state(FLEET[STATUS_CHUNK_SIZE]).status == {"taskState": "RUNNING"}
    assert poller.api_connected is True


@pytest.mark.asyncio
async def test_poll_robot_data_stops_on_short_page(client: AsyncMock, poller: DataPoller) -> None:
    client.get_robots.return_value = {
        "robots": [
            {"serialNumber": SN_1, "displayName": "Robot Alpha"},
            {"serialNumber": "GS999-9999-999-9999", "displayName": "Other"},
        ]
    }

    await poller.poll_robot_data_once()

    client.get_robots.assert_awaited_once_with(page=1, page_size=ROBOTS_PAGE_SIZE)
    assert poller.get_state(SN_1).robot_data == {
        "serialNumber": SN_1,
        "displayName": "Robot Alpha",
    }
    assert poller.get_state(SN_2).robot_data == {}


@pytest.mark.asyncio
async def test_poll_robot_data_pages_until_all_seen(client: AsyncMock, poller: DataPoller) -> None:
    full_page = [
        {"serialNumber": f"GS999-0000-000-{i:04d}"} for i in range(ROBOTS_PAGE_SIZE - 1)
    ] + [{"serialNumber": SN_1, "displayName": "Robot Alpha"}]
    second_page = [{"serialNumber": SN_2, "displayName": "Target1102"}] + [
        {"serialNumber": f"GS998-0000-000-{i:04d}"} for i in range(ROBOTS_PAGE_SIZE - 1)
    ]
    client.get_robots.side_effect = [{"robots": full_page}, {"robots": second_page}]

    await poller.poll_robot_data_once()

    assert client.get_robots.await_args_list == [
        call(page=1, page_size=ROBOTS_PAGE_SIZE),
        call(page=2, page_size=ROBOTS_PAGE_SIZE),
    ]
    assert poller.get_state(SN_1).robot_data["displayName"] == "Robot Alpha"
    assert poller.get_state(SN_2).robot_data["displayName"] == "Target1102"


@pytest.mark.asyncio
async def test_poll_robot_data_failure_keeps_cache(client: AsyncMock, poller: DataPoller) -> None:
    client.get_robots.side_effect = [
        {"robots": [{"serialNumber": SN_1, "displayName": "Robot Alpha"}]},
        None,
    ]
    await poller.poll_robot_data_once()

    await poller.poll_robot_data_once()

    assert poller.get_state(SN_1).robot_data["displayName"] == "Robot Alpha"
