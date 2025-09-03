# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import asyncio
from abc import ABC, abstractmethod

from .mir_api_v2 import MirApiV2
from tenacity import retry, wait_exponential_jitter, before_sleep_log, retry_if_exception_type
import httpx
import logging
import uuid


class MirMissionsGroupHandler(ABC):
    """Base class for missions group handling."""
        
    @abstractmethod
    async def start(self):
        """Start the temporary missions group."""
        pass
    
    @abstractmethod
    async def stop(self):
        """Stop the temporary missions group."""
        pass

    @abstractmethod
    async def setup_connector_missions(self):
        """Find and store the required missions and missions group, or create them if they don't
        exist.
        Called from the start() method but can be called manually to recreate the missions group.
        """
        pass
    
    @abstractmethod
    async def cleanup_connector_missions(self):
        """Delete the missions group."""
        pass

    @property
    def missions_group_id(self) -> str | None:
        """Get the missions group id for temporary missions."""
        return None

class NullMissionsGroupHandler(MirMissionsGroupHandler):
    """Bo-op object for missions group handling."""

    async def start(self):
        """Start the temporary missions group."""
        pass
    
    async def stop(self):
        """Stop the temporary missions group."""
        pass

    async def setup_connector_missions(self):
        """Setup the connector missions."""
        pass
    
    async def cleanup_connector_missions(self):
        """Cleanup the connector missions."""
        pass

class TmpMissionsGroupHandler(MirMissionsGroupHandler):
    """Temporary missions group handling."""
    
    
    # Connector missions group name
    # If a group with this name exists it will be used, otherwise it will be created
    # At shutdown, the group will be deleted
    MIR_INORBIT_MISSIONS_GROUP_NAME = "InOrbit Temporary Missions Group"

    # Remove missions created in the temporary missions group every 6 hours
    MISSIONS_GARBAGE_COLLECTION_INTERVAL_SECS = 6 * 60 * 60

    def __init__(self, mir_api: MirApiV2):
        super().__init__()
        
        self.mir_api = mir_api
        self._logger = logging.getLogger(name=self.__class__.__name__)
        
        # Missions group id for temporary missions
        # If None, it indicates the missions group has not been set up
        self._missions_group_id = None
        self._missions_group_id_lock = asyncio.Lock()

        # Background tasks
        self._bg_tasks: list[asyncio.Task] = []
    
    @property
    def missions_group_id(self) -> str | None:
        """Get the missions group id for temporary missions."""
        return self._missions_group_id

    async def start(self):
        """Start the temporary missions group."""
        # Start async setup and garbage collection for missions
        self._bg_tasks.append(asyncio.create_task(self.setup_connector_missions()))
        self._bg_tasks.append(asyncio.create_task(self._missions_garbage_collector()))
    
    async def stop(self):
        """Stop the temporary missions group."""
        for task in self._bg_tasks:
            task.cancel()
        if self._bg_tasks:
            await asyncio.gather(*self._bg_tasks, return_exceptions=True)
        self._bg_tasks.clear()
    
    @retry(
        wait=wait_exponential_jitter(max=10),
        before_sleep=before_sleep_log(logging.getLogger(__name__), logging.WARNING),
        retry=retry_if_exception_type(httpx.RequestError),
    )
    async def setup_connector_missions(self):
        """Find and store the required missions and missions group, or create them if they don't
        exist."""
        async with self._missions_group_id_lock:
            # If the missions group is not None it means it was already setup or it was deleted
            # intentionally and should not be set up again
            if self._missions_group_id is not None:
                return
        self._logger.info("Setting up connector missions")
        # Find or create the missions group
        mission_groups: list[dict] = await self.mir_api.get_mission_groups()
        group = next(
            (x for x in mission_groups if x["name"] == self.MIR_INORBIT_MISSIONS_GROUP_NAME), None
        )
        self._missions_group_id = group["guid"] if group is not None else str(uuid.uuid4())
        if group is None:
            self._logger.info(f"Creating mission group '{self.MIR_INORBIT_MISSIONS_GROUP_NAME}'")
            group = await self.mir_api.create_mission_group(
                feature=".",
                icon=".",
                name=self.MIR_INORBIT_MISSIONS_GROUP_NAME,
                priority=0,
                guid=self._missions_group_id,
            )
            self._logger.info(f"Mission group created with guid '{self._missions_group_id}'")
        else:
            self._logger.info(
                f"Found mission group '{self.MIR_INORBIT_MISSIONS_GROUP_NAME}' with "
                f"guid '{self._missions_group_id}'"
            )

    async def cleanup_connector_missions(self):
        """Delete the missions group created at startup"""
        async with self._missions_group_id_lock:
            # If the missions group id is None, it means it was not set up and there is nothing to
            # clean up. Change its value to indicate it should not be set up, in case there is a
            # running setup thread.
            if self._missions_group_id is None:
                self._missions_group_id = ""
                return
        self._logger.info("Cleaning up connector missions")
        self._logger.info(f"Deleting missions group {self._missions_group_id}")
        await self.mir_api.delete_mission_group(self._missions_group_id)
        
    async def _delete_unused_missions(self):
        """Delete all missions definitions in the temporary group that are not associated to
        pending or executing missions"""
        try:
            mission_defs = await self.mir_api.get_mission_group_missions(self._missions_group_id)
            missions_queue = await self.mir_api.get_missions_queue()
            # Do not delete definitions of missions that are pending or executing
            protected_mission_defs = [
                (await self.mir_api.get_mission(mission["id"]))["mission_id"]
                for mission in missions_queue
                if mission["state"].lower() in ["pending", "executing"]
            ]
            # Delete the missions definitions in the temporary group that are not
            # associated to pending or executing missions
            missions_to_delete = [
                mission["guid"]
                for mission in mission_defs
                if mission["guid"] not in protected_mission_defs
            ]
        except Exception as ex:
            self._logger.error(f"Failed to get missions for garbage collection: {ex}")
            return

        for mission_id in missions_to_delete:
            try:
                self._logger.info(f"Deleting mission {mission_id}")
                await self.mir_api.delete_mission_definition(mission_id)
            except Exception as ex:
                self._logger.error(f"Failed to delete mission {mission_id}: {ex}")

    async def _missions_garbage_collector(self):
        """Delete unused missions preiodically"""
        while True:
            await asyncio.sleep(self.MISSIONS_GARBAGE_COLLECTION_INTERVAL_SECS)
            await self._delete_unused_missions()
