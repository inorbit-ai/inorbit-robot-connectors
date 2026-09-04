# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Metrics recording behavior of OmronApiClient._request."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from inorbit_omron_connector.src.omron.api_client import OmronApiClient


def _client() -> OmronApiClient:
    config = SimpleNamespace(
        url="https://flowcore.example.com",
        username="user",
        password="pass",
        verify_ssl=False,
    )
    api = OmronApiClient(config)
    api.client = MagicMock(spec=httpx.AsyncClient)
    return api


@pytest.mark.asyncio
async def test_request_success_records_request_metric():
    api = _client()
    response = httpx.Response(200, request=httpx.Request("GET", "https://x/Robot/UpdatedSince"))
    api.client.request = AsyncMock(return_value=response)

    with patch(
        "inorbit_omron_connector.src.omron.api_client.record_upstream_http_request"
    ) as record:
        result = await api._request("GET", "/Robot/UpdatedSince?sinceTime=0")

    assert result is response
    record.assert_called_once()
    kwargs = record.call_args.kwargs
    assert kwargs["vendor"] == "flowcore"
    assert kwargs["method"] == "GET"
    assert kwargs["endpoint"] == "robot_updated_since"
    assert kwargs["duration_seconds"] >= 0


@pytest.mark.asyncio
async def test_request_http_error_records_error_metric_and_raises():
    api = _client()
    response = httpx.Response(500, request=httpx.Request("POST", "https://x/JobRequest"))
    api.client.request = AsyncMock(return_value=response)

    with patch(
        "inorbit_omron_connector.src.omron.api_client.record_upstream_http_error"
    ) as record:
        with pytest.raises(httpx.HTTPStatusError):
            await api._request("POST", "/JobRequest", json={})

    record.assert_called_once()
    kwargs = record.call_args.kwargs
    assert kwargs["vendor"] == "flowcore"
    assert kwargs["method"] == "POST"
    assert kwargs["endpoint"] == "job_request"
    assert kwargs["error_kind"] == "http_5xx"


@pytest.mark.asyncio
async def test_request_timeout_records_error_metric_and_raises():
    api = _client()
    api.client.request = AsyncMock(side_effect=httpx.ReadTimeout("slow"))

    with patch(
        "inorbit_omron_connector.src.omron.api_client.record_upstream_http_error"
    ) as record:
        with pytest.raises(httpx.ReadTimeout):
            await api._request("GET", "/JobCancel")

    assert record.call_args.kwargs["error_kind"] == "timeout"


@pytest.mark.asyncio
async def test_public_method_keeps_fallback_on_error():
    """get_data_store_value still swallows errors and returns [] (behavior unchanged)."""
    api = _client()
    api.client.request = AsyncMock(side_effect=httpx.ConnectError("down"))

    with patch("inorbit_omron_connector.src.omron.api_client.record_upstream_http_error"):
        assert await api.get_data_store_value("PoseX", "*") == []


@pytest.mark.asyncio
async def test_get_fleet_state_raises_on_transport_error():
    api = _client()
    api.client.request = AsyncMock(side_effect=httpx.ConnectError("boom"))

    with pytest.raises(httpx.ConnectError):
        await api.get_fleet_state()
