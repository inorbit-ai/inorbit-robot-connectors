# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Shared fixtures for tests that drive the connector against the mock ARCL server."""

import pytest
import pytest_asyncio

from inorbit_omron_connector.src.config.models import FlowCoreConnectorConfig, FlowCoreConfig
from inorbit_omron_connector.src.omron.mock_client import MockOmronClient
from inorbit_omron_connector.src.omron.mock_arcl_server import MockArclServer

@pytest_asyncio.fixture
async def mock_arcl(unused_tcp_port):
    server = MockArclServer(port=unused_tcp_port)
    await server.start()
    yield server
    await server.stop()

@pytest.fixture
def connector_config(unused_tcp_port):
    omron_config = FlowCoreConfig(
        url="https://mock.com", 
        password="mock",
        arcl_port=unused_tcp_port,
        arcl_password="omron"
    )
    return FlowCoreConnectorConfig(
        connector_type="flowcore",
        connector_config=omron_config,
        api_key="test_key",
        fleet=[{"robot_id": "Robot1", "fleet_robot_id": "Robot1_FlowCore"}]
    )

@pytest_asyncio.fixture
async def mock_omron():
    client = MockOmronClient()
    await client.connect()
    client.seed_robot("Robot1_FlowCore", status="Available", sub_status="Available", ip_address="127.0.0.1")
    return client
