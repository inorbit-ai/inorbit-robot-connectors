# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""
This file contains the Robot class that manages async polling loops for different data types
from the Gausium robot API.
"""

import asyncio
import logging
from typing import Coroutine

from .robot_api import RobotAPI


class Robot:
    """
    This class contains the main logic for fetching data from the robot.
    Each API endpoint is hit in a separate loop at its own specific frequency.
    The property accessors are used to get the latest fetched data from the robot.
    """

    def __init__(
        self,
        robot_api: RobotAPI,
        default_update_freq: float,
    ):
        self.logger = logging.getLogger(name=self.__class__.__name__)
        self._robot_api = robot_api
        self._stop_event = asyncio.Event()
        self._robot_status: dict = {}
        self._robot_status_v2: dict = {}
        self._task_reports: dict = {}
        self._robot_data: dict = {}
        self._robot_details: dict = {}
        self._default_update_freq = default_update_freq
        self._running_tasks: list[asyncio.Task] = []

    def start(self) -> None:
        """Start the tasks that fetch data from the robot."""
        self.logger.info("Starting polling loops")

        # Start the main status polling loop at default frequency
        self._run_in_loop(self._update_robot_status)
        self._run_in_loop(self._update_robot_status_v2)

        # Update non realtime data at a lower frequency (every minute)
        every_minute = 1 / 60
        self._run_in_loop(self._update_robot_data, frequency=every_minute)
        self._run_in_loop(self._update_robot_details, frequency=every_minute)

        # Start task reports polling at a lower frequency (every 5 seconds)
        self._run_in_loop(self._update_task_reports, frequency=0.2)

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

    async def _update_robot_status(self) -> None:
        """Fetch the robot status from the API."""
        try:
            self._robot_status = await self._robot_api.get_status()
            self.logger.debug("Robot status updated successfully")
        except Exception as e:
            self.logger.error(f"Error fetching robot status: {e}")
            # Keep the last known status on error

    async def _update_robot_status_v2(self) -> None:
        """Fetch the robot status from the API."""
        try:
            self._robot_status_v2 = await self._robot_api.get_status_v2()
            self.logger.debug("Robot status updated successfully")
        except Exception as e:
            self.logger.error(f"Error fetching robot status: {e}")
            # Keep the last known status on error

    async def _update_task_reports(self) -> None:
        """Fetch task reports from the API."""
        try:
            self._task_reports = await self._robot_api.get_task_reports(page=1, page_size=2)
            self.logger.debug("Task reports updated successfully")
        except Exception as e:
            self.logger.error(f"Error fetching task reports: {e}")
            # Keep the last known reports on error

    async def _update_robot_data(self) -> None:
        """Fetch robot-inherent data from the robot list API."""
        try:
            json = await self._robot_api.get_robot_list(
                filter=f"serialNumber%3D{self._robot_api.serial_number}",
                page_size=1,
            )
            self._robot_data = next(
                (
                    robot
                    for robot in json.get("robots", [])
                    if robot.get("serialNumber") == self._robot_api.serial_number
                ),
                {},
            )
            self.logger.debug("Robot data updated successfully")
        except Exception as e:
            self.logger.error(f"Error fetching robot data: {e}")
            # Keep the last known data on error

    async def _update_robot_details(self) -> None:
        """Fetch other robot details from the API."""
        try:
            self._robot_details = (await self._robot_api.get_robot_details()).get("data", {})
            self.logger.debug("Robot details updated successfully")
        except Exception as e:
            self.logger.error(f"Error fetching robot details: {e}")
            # Keep the last known details on error

    @property
    def status(self) -> dict:
        """Return the latest robot status"""
        return self._robot_status

    @property
    def status_v2(self) -> dict:
        """Return the latest robot status"""
        return self._robot_status_v2

    @property
    def task_reports(self) -> dict:
        """Return the latest task reports"""
        return self._task_reports

    @property
    def api_connected(self) -> bool:
        """Return whether the API connection is healthy.
        This is defined by whether the last API call succeeded, regardless of its status code"""
        return self._robot_api.last_call_successful

    @property
    def robot_data(self) -> dict:
        """Return the latest robot data"""
        return self._robot_data

    @property
    def robot_details(self) -> dict:
        """Return the latest robot details"""
        return self._robot_details

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
                        # Shorter sleep during errors to check stop_event more
                        # frequently
                        await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                # Exit cleanly when cancelled
                pass

        self._running_tasks.append(asyncio.create_task(loop()))
