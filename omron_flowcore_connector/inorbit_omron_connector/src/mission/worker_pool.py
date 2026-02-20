# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Worker pool extension for Omron mission execution."""

from __future__ import annotations

import logging
from typing import Any, override

from inorbit_edge_executor.mission import Mission
from inorbit_edge_executor.worker_pool import WorkerPool

from inorbit_omron_connector.src.omron.api_client import OmronApiClient
from inorbit_omron_connector.src.mission.tree_builder import OmronTreeBuilder
from inorbit_omron_connector.src.mission.behavior_tree import OmronBehaviorTreeBuilderContext
from inorbit_omron_connector.src.mission.translator import InOrbitToOmronTranslator
from inorbit_omron_connector.src.mission.datatypes import OmronInOrbitMission


class OmronWorkerPool(WorkerPool):
    """WorkerPool specialized for Omron FlowCore mission execution."""

    def __init__(
        self,
        *,
        api_client: OmronApiClient,
        robot_id_to_fleet_id: dict[str, str],
        mission_tracking: Any = None,
        **kwargs,
    ):
        self._logger = logging.getLogger(self.__class__.__name__)
        self._api_client = api_client
        self._robot_id_to_fleet_id = robot_id_to_fleet_id
        self._mission_tracking = mission_tracking
        
        super().__init__(behavior_tree_builder=OmronTreeBuilder(), **kwargs)

    @override
    def create_builder_context(self) -> OmronBehaviorTreeBuilderContext:
        """Create Omron-specific builder context."""
        return OmronBehaviorTreeBuilderContext(
            api_client=self._api_client,
            robot_id_to_fleet_id=self._robot_id_to_fleet_id,
            mission_tracking=self._mission_tracking,
        )

    @override
    def translate_mission(self, mission: Mission) -> OmronInOrbitMission:
        """Translate InOrbit mission to Omron format."""
        robot_id = mission.robot_id
        fleet_robot_id = self._robot_id_to_fleet_id.get(robot_id)

        self._logger.debug(
            f"Translating mission {mission.id} for robot {robot_id} (fleet ID {fleet_robot_id})"
        )

        return InOrbitToOmronTranslator.translate(
            mission=mission,
            fleet_robot_id=fleet_robot_id,
        )

    @override
    def deserialize_mission(self, serialized_mission: dict) -> OmronInOrbitMission:
        """Deserialize mission using Omron-specific mission type."""
        return OmronInOrbitMission.model_validate(serialized_mission)

