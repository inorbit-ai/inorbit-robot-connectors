# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import asyncio
import logging

LOGGER = logging.getLogger(__name__)

class MockArclServer:
    def __init__(self, host='127.0.0.1', port=7171, password="omron"):
        self.host = host
        self.port = port
        self.password = password
        self.server = None
        self.received_data = []
        self.clients = []
        self.stop_event = asyncio.Event()
        self.command_handlers = {}

    def register_command_handler(self, command_prefix: str, handler):
        """Registers a handler for a specific command prefix."""
        self.command_handlers[command_prefix] = handler

    async def handle_client(self, reader, writer):
        self.clients.append(writer)
        addr = writer.get_extra_info('peername')
        LOGGER.info(f"Client connected from {addr}")
        try:
            # Simulate Handshake
            writer.write(b"Welcome to Omron ARCL\r\n")
            writer.write(b"Enter password:")
            await writer.drain()

            # Verify Password
            password_data = await reader.readline() # Read password
            if not password_data:
                return
                
            received_password = password_data.decode().strip()
            if received_password != self.password:
                LOGGER.warning(f"Incorrect password: {received_password}")
                writer.close()
                await writer.wait_closed()
                return

            writer.write(b"End of commands\r\n")
            await writer.drain()

            # Echo Loop
            while not self.stop_event.is_set():
                data = await reader.readline()
                if not data:
                    break
                
                msg = data.decode().strip()
                self.received_data.append(msg)
                LOGGER.debug(f"Received: {msg}")
                
                for prefix, handler in self.command_handlers.items():
                    if msg.startswith(prefix):
                        try:
                            if asyncio.iscoroutinefunction(handler):
                                await handler(msg)
                            else:
                                handler(msg)
                        except Exception as e:
                            LOGGER.error(f"Error in command handler for {prefix}: {e}")
                
                writer.write(f"OK: {msg}\r\n".encode())
                await writer.drain()
        except Exception as e:
            LOGGER.error(f"Error handling client {addr}: {e}")
        finally:
            LOGGER.info(f"Client disconnected: {addr}")
            if writer in self.clients:
                self.clients.remove(writer)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def start(self, port=None):
        if port:
            self.port = port
        self.server = await asyncio.start_server(
            self.handle_client, self.host, self.port
        )
        LOGGER.info(f"Mock ARCL Server started on {self.host}:{self.port}")
        return self.server

    async def stop(self):
        self.stop_event.set()
        if self.server:
            self.server.close()
            try:
                await asyncio.wait_for(self.server.wait_closed(), timeout=2.0)
            except asyncio.TimeoutError:
                pass
        for client in self.clients:
            try:
                client.close()
                # Don't wait for clients to close in a mock
            except Exception:
                pass
        self.clients.clear()
        LOGGER.info("Mock ARCL Server stopped")
