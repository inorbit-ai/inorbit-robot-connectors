# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest
import asyncio
import pytest_asyncio
from inorbit_omron_connector.src.omron.arcl_client import ArclClient, CommandType
from inorbit_omron_connector.src.omron.mock_arcl_server import MockArclServer

# Fixtures

@pytest_asyncio.fixture
async def mock_server(unused_tcp_port):
    server = MockArclServer(port=unused_tcp_port)
    await server.start()
    yield server
    await server.stop()

@pytest_asyncio.fixture
async def client(unused_tcp_port):
    arcl = ArclClient('127.0.0.1', unused_tcp_port, 'omron')
    yield arcl
    await arcl.disconnect()

# Tests

@pytest.mark.asyncio
async def test_connection_flow(mock_server, client):
    """Test that client connects and sends password."""
    await client.connect()
    
    # Wait for connection
    try:
        await client.wait_for_connection(timeout=2.0)
    except asyncio.TimeoutError:
        pytest.fail("Client failed to connect to mock server")
        
    assert client.is_connected()

@pytest.mark.asyncio
async def test_login_failure(unused_tcp_port):
    """Test that client handles incorrect password."""
    server = MockArclServer(port=unused_tcp_port, password="right_password")
    await server.start()
    
    client = ArclClient('127.0.0.1', unused_tcp_port, 'wrong_password')
    await client.connect()
    
    # It should not connect
    await asyncio.sleep(1)
    assert not client.is_connected()
    
    await client.disconnect()
    await server.stop()

@pytest.mark.asyncio
async def test_reconnection(mock_server, unused_tcp_port):
    """Test that client reconnects if server drops."""
    # Use a short reconnect interval for testing
    client = ArclClient('127.0.0.1', unused_tcp_port, 'omron', reconnect_interval=0.1)
    await client.connect()
    await client.wait_for_connection(timeout=2.0)
    
    # Kill the server
    await mock_server.stop()
    
    # Client should detect loss
    await asyncio.sleep(0.5)
    assert not client.is_connected()
    
    # Restart server
    mock_server.stop_event.clear()
    await mock_server.start()
    
    # Client should eventually reconnect
    await client.wait_for_connection(timeout=2.0)
    assert client.is_connected()
    
    await client.disconnect()

@pytest.mark.asyncio
async def test_queue_processing(mock_server, client):
    """Test standard command sending."""
    await client.connect()
    await client.wait_for_connection(timeout=2.0)
    
    await client.go()
    await client.dock()
    
    # Give time for write loop to process
    await asyncio.sleep(0.5)
    
    # Check if mock server received them
    assert any("go" == cmd for cmd in mock_server.received_data)
    assert any("dock" == cmd for cmd in mock_server.received_data)

@pytest.mark.asyncio
async def test_set_block_cancellation_logic(client):
    """
    Test the specific logic: Set Block cancels Go/Clear.
    """
    # 1. Fill queue with mixed commands
    await client.go()                         # Type GO
    await client.clear_block_driving("Test")  # Type CLEAR
    await client.dock()                       # Type DOCK (Should stay)
    
    assert len(client._queue) == 3
    
    # 2. Add Set Block Driving
    await client.set_block_driving("Test", "Short", "Long") # Type SET_BLOCK
    
    # 3. Verify Queue
    # Expect: DOCK and SET_BLOCK only. (GO and CLEAR should be purged)
    
    final_queue = list(client._queue)
    assert len(final_queue) == 2
    
    # Check Item 1: DOCK (preserved)
    assert final_queue[0][0] == CommandType.DOCK
    
    # Check Item 2: SET_BLOCK (added)
    assert final_queue[1][0] == CommandType.SET_BLOCK
    assert 'abds "Test" "Short" "Long"' in final_queue[1][1]

@pytest.mark.asyncio
async def test_disconnect_cleanup(mock_server, client):
    await client.connect()
    await client.wait_for_connection(timeout=2.0)
    
    await client.disconnect()
    
    assert not client.is_connected()
    assert client._manager_task is None