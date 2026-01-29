"""
This file contains the Robot class that manages async polling loops for different data types
from the MiR robot API.
"""

import asyncio
import logging
from typing import Coroutine
import time

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
        enable_diagnostics: bool = True,
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
        self._enable_diagnostics = enable_diagnostics

        # Circuit breaker pattern for error handling
        self._consecutive_errors = 0
        self._max_consecutive_errors = 5
        self._backoff_time = 1.0  # Start with 1 second backoff
        self._max_backoff_time = 30.0  # Max 30 seconds backoff
        self._last_error_time = 0

    def start(self) -> None:
        """Start the tasks that fetch data from the robot."""
        self.logger.info("Starting polling loops")

        # Start the main status polling loop at default frequency
        self._run_in_loop(self._update_status)
        # Start metrics polling at a lower frequency (every 2 seconds)
        self._run_in_loop(self._update_metrics, frequency=0.5)
        # Start diagnostics polling at a lower frequency (every 2 seconds)
        # Note: diagnostics endpoint does not exist on v2 firmware
        if self._enable_diagnostics:
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
            self._handle_success()
        except Exception as e:
            self._handle_error(e, "robot status fetch")
            # Keep the last known status on error

    async def _update_metrics(self) -> None:
        """Fetch robot metrics from the API asynchronously."""
        try:
            metrics = await self._mir_api.get_metrics()
            self._metrics = metrics
            self._handle_success()
        except Exception as e:
            self._handle_error(e, "robot metrics fetch")
            # Keep the last known metrics on error

    async def _update_diagnostics(self) -> None:
        """Fetch robot diagnostics from the API asynchronously."""
        try:
            diagnostics = await self._mir_api.get_diagnostics()
            self._diagnostics = diagnostics
            self._handle_success()
        except Exception as e:
            self._handle_error(e, "robot diagnostics fetch")
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
    def grouped_vitals(self) -> dict:
        """Return the latest grouped vitals data sources"""
        return self._grouped_vitals

    @property
    def api_connected(self) -> bool:
        """Return whether the API connection is healthy.
        This is defined by whether the last API call succeeded, regardless of its status code
        """
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

                        # Apply backoff if we have consecutive errors
                        if self._consecutive_errors >= self._max_consecutive_errors:
                            current_time = time.time()
                            if current_time - self._last_error_time < self._backoff_time:
                                self.logger.debug(
                                    f"Circuit breaker active, backing off for {self._backoff_time}s"
                                )
                                await asyncio.sleep(self._backoff_time)
                                continue

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

    def _handle_success(self) -> None:
        """Handle successful API call - reset error counters"""
        if self._consecutive_errors > 0:
            self.logger.info(
                f"API connection recovered after {self._consecutive_errors} consecutive errors"
            )

        # Track API connection state changes
        if not getattr(self, "_api_connected", True):
            self.logger.info("Robot API connection established")
            self._api_connected = True

        self._consecutive_errors = 0
        self._backoff_time = 1.0  # Reset backoff time
        self._last_call_successful = True

    def _handle_error(self, error: Exception, operation: str) -> None:
        """Handle API error - implement circuit breaker logic"""
        self._last_call_successful = False
        self._consecutive_errors += 1

        # Track API connection state changes
        if getattr(self, "_api_connected", True):
            self.logger.warning("Robot API connection lost")
            self._api_connected = False
        self._last_error_time = time.time()

        # Exponential backoff with max limit
        self._backoff_time = min(self._backoff_time * 1.5, self._max_backoff_time)

        # Log with appropriate level based on error frequency
        if self._consecutive_errors == 1:
            self.logger.error(
                f"Error in {operation}: {type(error).__name__}: {error}", exc_info=True
            )
        elif self._consecutive_errors == self._max_consecutive_errors:
            self.logger.error(
                f"Circuit breaker activated after {self._consecutive_errors} consecutive "
                f"errors in {operation}. Backing off for {self._backoff_time}s"
            )
        elif self._consecutive_errors % 10 == 0:  # Log every 10th error to reduce noise
            self.logger.error(
                f"Still failing {operation} ({self._consecutive_errors} consecutive "
                f"errors): {type(error).__name__}: {error}"
            )
        else:
            self.logger.debug(
                f"Continuing error in {operation} ({self._consecutive_errors} "
                f"errors): {type(error).__name__}: {error}"
            )
