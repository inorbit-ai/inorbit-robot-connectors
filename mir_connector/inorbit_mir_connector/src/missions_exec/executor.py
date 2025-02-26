# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import logging
from inorbit_mir_connector.src.missions.exceptions import TranslationException
from inorbit_mir_connector.src.missions.inorbit import InOrbitAPI
from inorbit_mir_connector.src.missions.mission import Mission
from inorbit_mir_connector.src.mir_api.mir_api_base import MirApiBaseClass
from inorbit_mir_connector.src.missions_exec.datatypes import (
    MissionExecuteRequest,
    MissionCancelRequest,
    UpdateMissionRequest,
)
from inorbit_mir_connector.src.missions_exec.worker_pool import MirWorkerPool
from pydantic import ValidationError

# TODOs:
# - Implement feedback


class MissionsExecutor:

    def __init__(self, inorbit_api: InOrbitAPI, mir_api: MirApiBaseClass, loglevel: str = "INFO"):
        self._logger = logging.getLogger(self.__class__.__name__)
        self._logger.setLevel(loglevel)
        self._mir_api = mir_api
        self._inorbit_api = inorbit_api
        self._worker_pool = None
        self._started = False

    async def start(self):
        self._logger.debug("Starting MissionsExecutor")
        self._worker_pool = MirWorkerPool(self._mir_api, self._inorbit_api)
        await self._worker_pool.start()
        self._started = True

    async def execute_mission(self, request: MissionExecuteRequest):
        """Creates and submits a mission for execution.

        Args:
            request (MissionExecuteRequest): Request containing the mission details provided by
            InOrbit.
        """
        if not self._started:
            self._logger.error("MissionsExecutor not started")
            return

        self._logger.debug(
            f"Excecute mission request: missionId={request.mission_id}"
            f"{request.model_dump_json(exclude_none=True)}"
        )

        try:
            mission = Mission(
                id=request.mission_id,
                robot_id=request.robot_id,
                definition=request.mission_definition,
                arguments=request.arguments,
            )
        except ValidationError as e:
            self._logger.error(f"Failed to create mission: {e}")
            return

        try:
            return await self._worker_pool.submit_work(mission, request.options)
        except TranslationException:
            self._logger.error(f"Failed to translate mission {mission.id}")

    def cancel_mission(self, request: MissionCancelRequest):
        self._logger.warning("Cancel mission not implemented")

    def update_mission(self, request: UpdateMissionRequest):
        self._logger.warning("Update mission not implemented")
