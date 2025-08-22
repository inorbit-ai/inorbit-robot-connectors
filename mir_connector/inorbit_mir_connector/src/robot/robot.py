"""
This file contains the Robot class that manages async polling loops for different data types
from the MiR robot API.
"""

import asyncio
import logging
from typing import Coroutine

from inorbit_mir_connector.src.mir_api.mir_api_base import MirApiBaseClass


class Robot:
    """
    This class contains the main logic for fetching data from the robot.
    Each API endpoint is hit in a separate loop at its own specific frequency.
    The property accessors are used to get the latest fetched data from the robot.
    """

    def __init__(
        self,
        mir_api: MirApiBaseClass,
        default_update_freq: float,
    ):
        self.logger = logging.getLogger(name=self.__class__.__name__)
        self._mir_api = mir_api
        self._stop_event = asyncio.Event()
        self._status: dict = {}
        self._metrics: dict = {}
        self._diagnostics: dict = {}
        self._default_update_freq = default_update_freq
        self._running_tasks: list[asyncio.Task] = []
        self._last_call_successful: bool = True

    def start(self) -> None:
        """Start the tasks that fetch data from the robot."""
        self.logger.info("Starting polling loops")

        # Start the main status polling loop at default frequency
        self._run_in_loop(self._update_status)
        # Start metrics polling at a lower frequency (every 2 seconds)
        self._run_in_loop(self._update_metrics, frequency=0.5)
        # Start diagnostics polling at a lower frequency (every 2 seconds)
        self._run_in_loop(self._update_diagnostics, frequency=0.5)

        self.logger.debug(f"Started {len(self._running_tasks)} polling tasks")

    async def stop(self) -> None:
        """Stop the tasks that fetch data from the robot."""
        self.logger.info("Stopping polling loops")

        # Signal all tasks to stop
        self._stop_event.set()

        # Give tasks a chance to exit gracefully
        if self._running_tasks:
            try:
                # Wait for tasks to complete with a timeout
                done, pending = await asyncio.wait(
                    self._running_tasks,
                    timeout=1.0,  # Allow 1 second for graceful shutdown
                    return_when=asyncio.ALL_COMPLETED,
                )

                # Only cancel tasks that didn't finish in time
                for task in pending:
                    task.cancel()

                # Wait briefly for cancellations to process
                if pending:
                    await asyncio.wait(pending, timeout=0.5)

            except Exception as e:
                self.logger.error(f"Error during graceful shutdown: {e}")

        # Clear the task list
        self._running_tasks.clear()
        self.logger.info("Polling loops stopped")

    async def _update_status(self) -> None:
        """Fetch the robot status from the API asynchronously."""
        try:
            status = await self._mir_api.get_status()
            self._status = status
            self._last_call_successful = True
            self.logger.debug("Robot status updated successfully")
        except Exception as e:
            self._last_call_successful = False
            self.logger.error(f"Error fetching robot status: {e}")
            # Keep the last known status on error

    async def _update_metrics(self) -> None:
        """Fetch robot metrics from the API asynchronously."""
        try:
            metrics = await self._mir_api.get_metrics()
            self._metrics = metrics
            self._last_call_successful = True
            self.logger.debug("Robot metrics updated successfully")
        except Exception as e:
            self._last_call_successful = False
            self.logger.error(f"Error fetching robot metrics: {e}")
            # Keep the last known metrics on error

    async def _update_diagnostics(self) -> None:
        """Fetch robot diagnostics from the API asynchronously."""
        try:
            diagnostics = await self._mir_api.get_diagnostics()
            self._diagnostics = diagnostics
            self._last_call_successful = True
            self.logger.debug("Robot diagnostics updated successfully")
        except Exception as e:
            self._last_call_successful = False
            self.logger.error(f"Error fetching robot diagnostics: {e}")
            # Keep the last known diagnostics on error

    @property
    def status(self) -> dict:
        """Return the latest robot status"""
        return self._status

    @property
    def metrics(self) -> dict:
        """Return the latest robot metrics"""
        return self._metrics

    @property
    def diagnostics(self) -> dict:
        """Return the latest robot diagnostics"""
        return self._diagnostics

    @property
    def api_connected(self) -> bool:
        """Return whether the API connection is healthy.
        This is defined by whether the last API call succeeded, regardless of its status code"""
        return self._last_call_successful

    def _run_in_loop(self, coro: Coroutine, frequency: float | None = None) -> None:
        """Run a coroutine in a loop at a specified frequency. If no frequency is
        provided, the default update frequency will be used."""

        async def loop():
            try:
                while not self._stop_event.is_set():
                    try:
                        # Check stop_event between each iteration
                        if self._stop_event.is_set():
                            break

                        await asyncio.gather(
                            coro(),
                            asyncio.sleep(1 / (frequency or self._default_update_freq)),
                        )
                    except asyncio.CancelledError:
                        # Handle cancellation gracefully
                        break
                    except Exception as e:
                        self.logger.error(f"Error in loop running {coro.__name__}: {e}")
                        # Shorter sleep during errors to check stop_event more frequently
                        await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                # Exit cleanly when cancelled
                pass

        self._running_tasks.append(asyncio.create_task(loop()))
