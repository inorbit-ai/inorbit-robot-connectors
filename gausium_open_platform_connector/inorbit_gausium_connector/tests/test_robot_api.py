# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import httpx
import pytest
import pytest_asyncio
from inorbit_gausium_connector.src.robot import RobotAPI
from inorbit_gausium_connector.src.robot.base_api_client import JWT
from pydantic import HttpUrl


@pytest_asyncio.fixture
async def robot_api():
    robot_api_url = HttpUrl("http://example.com/")
    api = RobotAPI(
        base_url=robot_api_url,
        serial_number="robotsn",
        client_id="clientid",
        client_secret="clientsecret",
        access_key_secret="accesskeysecret",
    )
    # Mock the authentication to avoid actual HTTP calls
    api.token = JWT(
        access_token="mock_token",
        refresh_token="mock_refresh",
        expires_at_ms=9999999999999,  # Far future expiry
    )
    # Set up the authorization header
    api.api_client.headers.update(
        {
            "Authorization": f"Bearer {api.token.access_token}",
            "Content-Type": "application/json",
        }
    )
    yield api
    await api.close()


@pytest.mark.asyncio
async def test_http_error(robot_api: RobotAPI, httpx_mock):
    httpx_mock.add_response(
        method="GET", url="http://example.com/v1alpha1/robots/robotsn/status", status_code=500
    )
    with pytest.raises(httpx.HTTPStatusError):
        await robot_api.get_status()
