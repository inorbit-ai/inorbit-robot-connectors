# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Tests for `gausium_open_platform_connector.src.api.client`."""

from __future__ import annotations

import asyncio
import json
import logging

import httpx
import pytest
import pytest_asyncio
from pytest_httpx import HTTPXMock

from gausium_open_platform_connector.src.api.auth import REFETCH_MIN_INTERVAL_SECS
from gausium_open_platform_connector.src.api.client import GausiumApiClient
from gausium_open_platform_connector.src.commands import (
    RemoteNavigationCommandType,
    RemoteTaskCommandType,
)

BASE_URL = "https://openapi.example.com/"
SN_1 = "GS000-0000-000-0001"
SN_2 = "GS000-0000-000-0002"

OAUTH_URL = f"{BASE_URL}gas/api/v1alpha1/oauth/token"
# `expires_in` is the value the live API returns: an absolute epoch-ms deadline, ignored
TOKEN_RESPONSE = {"access_token": "tok-1", "refresh_token": "ref-1", "expires_in": 1787665295159}

STATUS_V1 = {
    "robotStatuses": [
        {
            "serialNumber": SN_1,
            "name": f"robots/{SN_1}",
            "taskState": "IDLE",
            "online": True,
            "speedKilometerPerHour": 0,
            "battery": {"charging": False, "powerPercentage": 100},
            "localizationInfo": {
                "localizationState": "LOST",
                "map": {"id": "map-1", "name": "floor_1"},
            },
        },
        {"serialNumber": SN_2, "taskState": "RUNNING", "online": True},
    ]
}

STATUS_V2 = {
    "robotStatus": [
        {
            "serialNumber": SN_1,
            "taskState": "IDLE",
            "online": True,
            "localizationInfo": {
                "localizationState": "LOST",
                "map": {
                    "id": "map-1",
                    "name": "floor_1",
                    "version": "maps/de3c27cf/versions/1ee75251",
                },
            },
        }
    ]
}


@pytest_asyncio.fixture()
async def client(httpx_mock: HTTPXMock) -> GausiumApiClient:
    """A connected client with the initial OAuth token already fetched."""
    httpx_mock.add_response(method="POST", url=OAUTH_URL, json=TOKEN_RESPONSE)
    api_client = GausiumApiClient(BASE_URL, "client-id", "client-secret", "access-key")
    await api_client.connect()
    yield api_client
    await api_client.close()


@pytest.mark.asyncio
async def test_connect_fetches_token(client: GausiumApiClient, httpx_mock: HTTPXMock) -> None:
    request = httpx_mock.get_request(url=OAUTH_URL)
    assert json.loads(request.content) == {
        "grant_type": "urn:gaussian:params:oauth:grant-type:open-access-token",
        "client_id": "client-id",
        "client_secret": "client-secret",
        "open_access_key": "access-key",
    }


@pytest.mark.asyncio
async def test_requests_inject_bearer_header(
    client: GausiumApiClient, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(json=STATUS_V1)

    await client.batch_status_v1([SN_1, SN_2])

    request = httpx_mock.get_requests()[-1]
    assert request.headers["Authorization"] == "Bearer tok-1"


@pytest.mark.asyncio
async def test_token_is_not_refetched_on_a_schedule(
    client: GausiumApiClient, httpx_mock: HTTPXMock
) -> None:
    # The vendor's `expires_in` is an absolute epoch-ms deadline, so a client-side expiry
    # computed from it can only ever disagree with the server. Nothing but a 401 refetches.
    httpx_mock.add_response(json=STATUS_V1, is_reusable=True)

    await client.batch_status_v1([SN_1])
    await client.batch_status_v1([SN_1])

    assert len(httpx_mock.get_requests(url=OAUTH_URL)) == 1
    assert httpx_mock.get_requests()[-1].headers["Authorization"] == "Bearer tok-1"


@pytest.mark.asyncio
async def test_concurrent_requests_fetch_token_once(
    client: GausiumApiClient, httpx_mock: HTTPXMock
) -> None:
    client._auth._token = None
    httpx_mock.add_response(
        method="POST",
        url=OAUTH_URL,
        json={"access_token": "tok-2", "refresh_token": "ref-2"},
    )
    httpx_mock.add_response(json=STATUS_V1, is_reusable=True)

    await asyncio.gather(client.batch_status_v1([SN_1]), client.batch_status_v1([SN_1]))

    # One request from the fixture's connect() plus exactly one shared refetch
    assert len(httpx_mock.get_requests(url=OAUTH_URL)) == 2
    refetch_request = httpx_mock.get_requests(url=OAUTH_URL)[-1]
    assert json.loads(refetch_request.content)["grant_type"] == (
        "urn:gaussian:params:oauth:grant-type:open-access-token"
    )


@pytest.mark.asyncio
async def test_401_refetches_token_and_retries(
    client: GausiumApiClient, httpx_mock: HTTPXMock
) -> None:
    # The server can drop a token the client still considers valid
    client._auth._last_fetch -= REFETCH_MIN_INTERVAL_SECS
    httpx_mock.add_response(status_code=401)
    httpx_mock.add_response(method="POST", url=OAUTH_URL, json={"access_token": "tok-2"})
    httpx_mock.add_response(json=STATUS_V1)

    result = await client.batch_status_v1([SN_1])

    assert result is not None
    assert httpx_mock.get_requests()[-1].headers["Authorization"] == "Bearer tok-2"


@pytest.mark.asyncio
async def test_401_refetch_is_rate_limited(client: GausiumApiClient, httpx_mock: HTTPXMock) -> None:
    client._auth._last_fetch -= REFETCH_MIN_INTERVAL_SECS
    httpx_mock.add_response(method="POST", url=OAUTH_URL, json={"access_token": "tok-2"})
    httpx_mock.add_response(status_code=401, is_reusable=True)

    assert await client.batch_status_v1([SN_1]) is None
    assert await client.batch_status_v1([SN_1]) is None

    # A 401 a new token cannot fix must not spin the OAuth endpoint
    assert len(httpx_mock.get_requests(url=OAUTH_URL)) == 2  # connect + one refetch


@pytest.mark.asyncio
async def test_repeated_failures_log_only_state_changes(
    client: GausiumApiClient, httpx_mock: HTTPXMock, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        httpx_mock.add_response(status_code=500, is_reusable=True)
        for _ in range(3):
            await client.batch_status_v1([SN_1])
        httpx_mock.reset()
        httpx_mock.add_response(status_code=503)
        await client.batch_status_v1([SN_1])
        httpx_mock.reset()
        httpx_mock.add_response(json=STATUS_V1)
        await client.batch_status_v1([SN_1])

    # No URL in the line: its `names=` parameter per robot is what made this unbounded
    assert [record.getMessage() for record in caplog.records] == [
        "status_v1_batch failed: 500",
        "status_v1_batch failed: 503",
        "status_v1_batch recovered after 4 failures over 0:00:00",
    ]


@pytest.mark.asyncio
async def test_batch_status_v1(client: GausiumApiClient, httpx_mock: HTTPXMock) -> None:
    # `names` must be a repeated query param: a comma-joined list 403s on the live API
    url = f"{BASE_URL}v1alpha1/robots/-/status:batchGet?names={SN_1}&names={SN_2}"
    httpx_mock.add_response(method="GET", url=url, json=STATUS_V1)

    result = await client.batch_status_v1([SN_1, SN_2])

    assert set(result) == {SN_1, SN_2}
    assert result[SN_1]["taskState"] == "IDLE"
    assert result[SN_2]["taskState"] == "RUNNING"


@pytest.mark.asyncio
async def test_batch_status_v2_uses_get_with_json_body(
    client: GausiumApiClient, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}openapi/v2alpha1/s/robots/*/status:batchGet",
        match_json={"names": [SN_1, SN_2]},
        json=STATUS_V2,
    )

    result = await client.batch_status_v2([SN_1, SN_2])

    assert set(result) == {SN_1}
    assert result[SN_1]["localizationInfo"]["map"]["name"] == "floor_1"


@pytest.mark.asyncio
async def test_data_methods_return_none_on_http_error(
    client: GausiumApiClient, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(status_code=500)
    httpx_mock.add_response(status_code=404)

    assert await client.batch_status_v1([SN_1]) is None
    assert await client.get_task_reports_v2(SN_1) is None


@pytest.mark.asyncio
async def test_get_robots_returns_raw_response(
    client: GausiumApiClient, httpx_mock: HTTPXMock
) -> None:
    payload = {
        "robots": [
            {
                "serialNumber": SN_1,
                "displayName": "Robot Alpha",
                "modelFamilyCode": "50",
                "modelTypeCode": "Scrubber 50H",
                "online": True,
                "softwareVersion": "B-47-4p-20260714",
            }
        ]
    }
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}v1alpha1/robots?page=2&pageSize=100&relation=cugrup",
        json=payload,
    )

    assert await client.get_robots(page=2) == payload


@pytest.mark.asyncio
async def test_get_task_reports_v2(client: GausiumApiClient, httpx_mock: HTTPXMock) -> None:
    reports = [
        {
            "id": "e4dfb0fb-81bd-4b10-9982-fd6f4f3b3d48",
            "robotSerialNumber": SN_1,
            "completionPercentage": 0.3,
            "durationSeconds": 2904,
            "taskEndStatus": 1,
        }
    ]
    httpx_mock.add_response(
        method="GET",
        url=f"{BASE_URL}openapi/v2alpha1/robots/{SN_1}/taskReports?page=1&pageSize=10",
        json={"robotTaskReports": reports, "page": 1, "pageSize": 10, "total": 1},
    )

    assert await client.get_task_reports_v2(SN_1) == reports


@pytest.mark.asyncio
async def test_get_report_map_images(client: GausiumApiClient, httpx_mock: HTTPXMock) -> None:
    images = [{"url": "https://example.com/0", "map_image_id": 0}]
    httpx_mock.add_response(
        method="POST",
        url=f"{BASE_URL}openapi-server/v1/api/task/report/map-images/query",
        match_json={"robotSn": SN_1, "taskReportId": "report-1"},
        json={"code": 0, "data": images, "msg": "SUCCESS"},
    )

    assert await client.get_report_map_images(SN_1, "report-1") == images


@pytest.mark.asyncio
async def test_get_report_map_images_failure_returns_none(
    client: GausiumApiClient, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(method="POST", status_code=500)

    assert await client.get_report_map_images(SN_1, "report-1") is None


@pytest.mark.asyncio
async def test_get_map_image(client: GausiumApiClient, httpx_mock: HTTPXMock) -> None:
    download_uri = "https://blob.example.com/maps/map.png?sig=abc"
    httpx_mock.add_response(
        method="GET",
        url=httpx.URL(
            f"{BASE_URL}openapi/v2alpha1/robots/{SN_1}/map",
            params={"mapId": "map-id", "mapName": "floor_1", "mapVersion": "v1"},
        ),
        json={"downloadUri": download_uri},
    )
    httpx_mock.add_response(method="GET", url=download_uri, content=b"\x89PNG-bytes")

    result = await client.get_map_image(SN_1, "map-id", "floor_1", "v1")

    assert result == b"\x89PNG-bytes"
    # The pre-signed URI must be fetched without the Bearer header
    assert "Authorization" not in httpx_mock.get_request(url=download_uri).headers


@pytest.mark.asyncio
async def test_retry_on_connect_error(client: GausiumApiClient, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_exception(httpx.ConnectError("boom"))
    httpx_mock.add_exception(httpx.ConnectError("boom"))
    httpx_mock.add_response(json=STATUS_V1)

    result = await client.batch_status_v1([SN_1])

    assert result is not None
    # 1 oauth call + 3 attempts
    assert len(httpx_mock.get_requests()) == 4


@pytest.mark.asyncio
async def test_no_retry_on_http_status_error(
    client: GausiumApiClient, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(status_code=500)

    assert await client.batch_status_v1([SN_1]) is None
    assert len(httpx_mock.get_requests()) == 2  # 1 oauth call + 1 attempt


@pytest.mark.asyncio
async def test_send_remote_task_command(client: GausiumApiClient, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="POST", url=f"{BASE_URL}v1alpha1/robots/{SN_1}/commands", json={}
    )

    await client.send_remote_task_command(SN_1, RemoteTaskCommandType.PAUSE_TASK)

    request = httpx_mock.get_requests()[-1]
    assert json.loads(request.content) == {
        "serialNumber": SN_1,
        "remoteTaskCommandType": "PAUSE_TASK",
    }


@pytest.mark.asyncio
async def test_send_remote_navigation_command(
    client: GausiumApiClient, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(
        method="POST", url=f"{BASE_URL}v1alpha1/robots/{SN_1}/commands", json={}
    )

    await client.send_remote_navigation_command(
        SN_1, RemoteNavigationCommandType.CROSS_NAVIGATE, {"x": 1}
    )

    request = httpx_mock.get_requests()[-1]
    assert json.loads(request.content) == {
        "serialNumber": SN_1,
        "remoteNavigationCommandType": "CROSS_NAVIGATE",
        "commandParameter": {"x": 1},
    }


@pytest.mark.asyncio
async def test_create_nosite_task(client: GausiumApiClient, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="POST", url=f"{BASE_URL}openapi/v2alpha1/robotCommand/tempTask:send", json={}
    )

    await client.create_nosite_task(
        SN_1, "task", "map-id", "floor_1", "area-1", "清洗", loop=True, loop_count=2
    )

    request = httpx_mock.get_requests()[-1]
    assert json.loads(request.content) == {
        "productId": SN_1,
        "tempTaskCommand": {
            "taskName": "task",
            "cleaningMode": "清洗",
            "loop": "true",
            "loopCount": "2",
            "mapName": "floor_1",
            "startParam": {"mapId": "map-id", "areaId": "area-1"},
        },
    }


@pytest.mark.asyncio
async def test_command_methods_raise_on_http_error(
    client: GausiumApiClient, httpx_mock: HTTPXMock
) -> None:
    httpx_mock.add_response(status_code=500)

    with pytest.raises(httpx.HTTPStatusError):
        await client.send_remote_task_command(SN_1, RemoteTaskCommandType.STOP_TASK)
