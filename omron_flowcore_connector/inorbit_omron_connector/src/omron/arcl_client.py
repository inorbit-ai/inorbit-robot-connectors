# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import asyncio
import logging
from collections import deque
from enum import Enum, auto
from typing import Optional

# Configure logging
LOGGER = logging.getLogger(__name__)

class CommandType(Enum):
    GENERIC = auto()
    GO = auto()
    DOCK = auto()
    UNDOCK = auto()
    SET_BLOCK = auto()
    CLEAR_BLOCK = auto()

class ArclClient:
    def __init__(
        self, 
        host: str, 
        port: int, 
        password: str, 
        connection_timeout: int = 10,
        reconnect_interval: int = 5
    ):
        self.host = host
        self.port = port
        self.password = password
        self.timeout = connection_timeout
        self.reconnect_interval = reconnect_interval
        
        self._shutdown_event = asyncio.Event()
        self._connected_event = asyncio.Event()
        
        # Custom Queue Management
        self._queue: deque = deque()
        self._queue_lock = asyncio.Lock()
        self._new_item_event = asyncio.Event()
        
        # Internal tasks
        self._manager_task: Optional[asyncio.Task] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._reader: Optional[asyncio.StreamReader] = None

    async def connect(self):
        """Starts the connection manager loop."""
        if self._manager_task and not self._manager_task.done():
            LOGGER.warning("Connection manager already running.")
            return

        self._shutdown_event.clear()
        self._manager_task = asyncio.create_task(self._connection_manager())
        LOGGER.info("ARCL Client task started.")

    async def disconnect(self):
        """Stops the loop and closes connections."""
        LOGGER.info("Disconnecting...")
        self._shutdown_event.set()
        
        # Wake up the queue processor so it can exit
        self._new_item_event.set()
        
        if self._manager_task:
            try:
                await self._manager_task
            except asyncio.CancelledError:
                pass
            self._manager_task = None
        
        await self._close_socket()
        LOGGER.info("ARCL Client disconnected.")

    async def _close_socket(self):
        """Safely closes the socket."""
        self._connected_event.clear()
        if self._writer:
            try:
                self._writer.close()
                await asyncio.wait_for(self._writer.wait_closed(), timeout=2.0)
            except Exception:
                pass
            self._writer = None
            self._reader = None

    async def _connection_manager(self):
        """
        Main Loop:
        1. Connects
        2. Spawns Reader (Keepalive) & Writer (Queue Consumer)
        3. Restarts on failure
        """
        while not self._shutdown_event.is_set():
            try:
                LOGGER.info(f"Connecting to socket {self.host}:{self.port}...")
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self.port), 
                    timeout=self.timeout
                )
                LOGGER.info(f"Socket connected to {self.host}:{self.port}")
                
                # Read until we see "Enter password:"
                LOGGER.info("Waiting for ARCL Password prompt...")
                await asyncio.wait_for(self._read_until_prompt(b"Enter password:"), timeout=max(10, self.timeout))
                LOGGER.info("Password prompt received.")
                
                self._writer.write(f"{self.password}\r\n".encode())
                await self._writer.drain()
                
                # Wait for login confirmation or command prompt
                async def _verify_login():
                    while True:
                        line = await self._reader.readline()
                        if not line:
                            raise PermissionError("ARCL Login Failed: Connection closed (Invalid Password)")
                        
                        msg = line.decode('utf-8', errors='ignore').strip()
                        LOGGER.debug(f"Login RX: {msg}")
                        
                        if "End of commands" in msg:
                            return

                # Enforce timeout on the login verification phase
                await asyncio.wait_for(_verify_login(), timeout=self.timeout)
                
                LOGGER.info("Login successful. Connection established.")
                self._connected_event.set()

                # Run Reader and Writer concurrently
                reader_task = asyncio.create_task(self._read_loop())
                writer_task = asyncio.create_task(self._write_loop())

                # Wait for either to fail/finish, or shutdown event
                done, pending = await asyncio.wait(
                    [reader_task, writer_task, asyncio.create_task(self._shutdown_event.wait())],
                    return_when=asyncio.FIRST_COMPLETED
                )

                # Clean up tasks
                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                
                # Check exceptions
                for task in done:
                    if not task.cancelled() and task.exception():
                        LOGGER.error(f"Task failed with: {task.exception()}")

            except PermissionError as e:
                LOGGER.error(f"Permission error: {e}")
            except (OSError, asyncio.TimeoutError) as e:
                LOGGER.error(f"Connection error: {type(e).__name__}: {e}")
            except Exception as e:
                LOGGER.exception(f"Unexpected error in connection manager: {type(e).__name__}: {e}")
            finally:
                await self._close_socket()
            
            if not self._shutdown_event.is_set():
                LOGGER.info(f"Reconnecting in {self.reconnect_interval} seconds...")
                await asyncio.sleep(self.reconnect_interval)

    async def _read_until_prompt(self, prompt: bytes):
        """Reads stream until specific bytes are found."""
        if not self._reader:
            return
        
        buffer = b""
        while prompt not in buffer:
            chunk = await self._reader.read(1024)
            if not chunk:
                LOGGER.debug(f"Stream closed while waiting for {prompt}. Buffer so far: {buffer}")
                raise ConnectionResetError("Remote closed connection during handshake")
            
            # Log all raw output as debug logs
            LOGGER.debug(f"ARCL RX (handshake): {chunk}")
            
            buffer += chunk
            LOGGER.debug(f"Handshake buffer so far: {buffer}")

    async def _read_loop(self):
        """
        Constantly reads from robot to detect disconnection.
        Also parses incoming status messages.
        """
        while not self._shutdown_event.is_set():
            if not self._reader:
                break
            
            line = await self._reader.readline()
            if not line:
                raise ConnectionResetError("Robot closed connection (EOF)")
            
            msg = line.decode('utf-8', errors='ignore').strip()
            LOGGER.debug(f"RX: {msg}")

    async def _write_loop(self):
        """
        Consumes the command queue and sends to robot.
        Waits for _new_item_event or _shutdown_event.
        """
        while not self._shutdown_event.is_set():
            # Wait for an item or signal
            await self._new_item_event.wait()
            
            # If shutdown triggered while waiting
            if self._shutdown_event.is_set():
                break

            cmd_str = None
            
            # Pop item safely
            async with self._queue_lock:
                if self._queue:
                    # item structure: (CommandType, raw_string)
                    _, cmd_str = self._queue.popleft()
                
                if not self._queue:
                    self._new_item_event.clear()

            if cmd_str and self._writer:
                try:
                    LOGGER.info(f"TX: {cmd_str.strip()}")
                    self._writer.write(cmd_str.encode())
                    await self._writer.drain()
                except OSError as e:
                    LOGGER.error(f"Failed to write: {e}")
                    raise e # This will kill the writer_task and trigger reconnection

    # --- Queue Logic ---

    async def _enqueue_command(self, cmd_type: CommandType, command_str: str):
        """
        Adds command to queue with specific logic:
        - If SET_BLOCK is added, remove any pending CLEAR_BLOCK or GO commands.
        """
        async with self._queue_lock:
            if cmd_type == CommandType.SET_BLOCK:
                # Filter out Cancelable commands
                original_len = len(self._queue)
                self._queue = deque(
                    item for item in self._queue 
                    if item[0] not in (CommandType.CLEAR_BLOCK, CommandType.GO)
                )
                removed_count = original_len - len(self._queue)
                if removed_count > 0:
                    LOGGER.warning(f"SET_BLOCK priority: Removed {removed_count} pending GO/CLEAR commands.")

            self._queue.append((cmd_type, command_str))
            self._new_item_event.set()

    # --- High Level Methods ---

    async def set_block_driving(self, name: str, short_desc: str, long_desc: str):
        """
        Stops the robot immediately, pausing its current job.
        The implementation uses 'abds' which stands for 'Application Block Driving Set'.
        """
        cmd = f'abds "{name}" "{short_desc}" "{long_desc}"\r\n'
        await self._enqueue_command(CommandType.SET_BLOCK, cmd)

    async def clear_block_driving(self, name: str):
        """Clears a driving block."""
        cmd = f'abdc {name}\r\n'
        await self._enqueue_command(CommandType.CLEAR_BLOCK, cmd)

    async def go(self):
        """Instructs the robot to continue immediately (resume)."""
        await self._enqueue_command(CommandType.GO, "go\r\n")

    async def dock(self):
        """Docks the robot."""
        await self._enqueue_command(CommandType.DOCK, "dock\r\n")

    async def undock(self):
        """Undocks the robot."""
        await self._enqueue_command(CommandType.UNDOCK, "undock\r\n")

    async def shutdown_robot(self):
        """Shuts down the AMR OS."""
        await self._enqueue_command(CommandType.GENERIC, "shutdown\r\n")

    def is_connected(self) -> bool:
        return self._connected_event.is_set()

    async def wait_for_connection(self, timeout: float = None):
        """Waits until the client is connected."""
        await asyncio.wait_for(self._connected_event.wait(), timeout=timeout)
