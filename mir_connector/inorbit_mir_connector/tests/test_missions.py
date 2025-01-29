# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

from unittest import mock
from unittest.mock import AsyncMock, MagicMock
from inorbit_mir_connector.src.connector import Mir100Connector
from inorbit_mir_connector.src.missions.datatypes import (
    MissionDefinition,
    MissionRuntimeOptions,
    MissionStepPoseWaypoint,
    MissionTask,
    Pose,
)
from inorbit_mir_connector.src.missions.mission import Mission
from inorbit_mir_connector.src.missions_exec.datatypes import (
    MissionDefinitionMiR,
    MissionExecuteRequest,
)
from inorbit_mir_connector.src.missions_exec.executor import MissionsExecutor
from inorbit_mir_connector.src.missions_exec.worker_pool import MirWorkerPool
import pytest


@pytest.fixture
def example_request():
    return MissionExecuteRequest(
        missionId="ac7af1e4-0721-4130-8e1c-80371e16bdf6",
        robotId="mir100-1",
        missionDefinition=MissionDefinitionMiR(
            label="Test Mission",
            steps=[
                MissionStepPoseWaypoint(
                    label="Move to waypoint",
                    timeoutSecs=60.0,
                    completeTask="Move to waypoint",
                    waypoint=Pose(
                        x=9.892293709504171,
                        y=5.018981943828619,
                        theta=0.0,
                        frameId="map",
                        waypointId="test-waypoint",
                        properties=None,
                    ),
                )
            ],
            selector={"robot": {"tagIds": ["f-hPYUnWQMUyMmxT"]}},
        ),
        missionArgs={},
        options=MissionRuntimeOptions(
            startMode=None,
            endMode=None,
            useLocks=False,
            waypointsDistanceTolerance=None,
            waypointsAngularTolerance=None,
        ),
    )


def create_mission_command(callback_handler_kwargs):
    callback_handler_kwargs["command_name"] = "customCommand"
    callback_handler_kwargs["args"] = [
        "executeMissionAction",
        [
            "robotId",
            "mir100-1",
            "missionId",
            "ac7af1e4-0721-4130-8e1c-80371e16bdf6",
            "missionArgs",
            "{}",
            "options",
            "{}",
            "missionDefinition",
            '{"label":"Test Mission","selector":{"robot":{"tagIds":["f-hPYUnWQMUyMmxT"]}},"steps":[{"label":"Move to waypoint","timeoutSecs":60,"waypoint":{"x":9.892293709504171,"y":5.018981943828619,"theta":0,"frameId":"map","waypointId":"test-waypoint"},"completeTask":"Move to waypoint"}]}',
        ],
    ]
    return callback_handler_kwargs


def test_mission_is_executed(connector: Mir100Connector, callback_kwargs, example_request):
    create_mission_command(callback_kwargs)
    connector.missions_executor.execute_mission = AsyncMock()
    connector._inorbit_command_handler(**callback_kwargs)
    connector.missions_executor.execute_mission.assert_called_once_with(example_request)


@pytest.mark.asyncio
async def test_mission_is_submitted(example_request):
    executor = MissionsExecutor(
        inorbit_api=MagicMock(),
        mir_api=MagicMock(),
        loglevel="DEBUG",
    )
    await executor.start()
    assert isinstance(executor._worker_pool, MirWorkerPool)
    executor._worker_pool.submit_work = AsyncMock()
    await executor.execute_mission(example_request)
    executor._worker_pool.submit_work.assert_called_once()


def test_mission_translator():
    inorbit_mission = Mission(
        id="ac7af1e4-0721-4130-8e1c-80371e16bdf6",
        robot_id="mir100-1",
        definition=MissionDefinitionMiR(
            label="Test Mission",
            steps=[
                MissionStepPoseWaypoint(
                    label="Move to waypoint",
                    timeout_secs=60.0,
                    complete_task="Move to waypoint",
                    waypoint=Pose(
                        x=9.892293709504171,
                        y=5.018981943828619,
                        theta=0.0,
                        frame_id="map",
                        waypointId="test-waypoint",
                        properties=None,
                    ),
                )
            ],
            selector={"robot": {"tagIds": ["f-hPYUnWQMUyMmxT"]}},
        ),
        arguments={},
        tasks_list=[
            MissionTask(
                taskId="Move to waypoint",
                label="Move to waypoint",
                in_progress=False,
                completed=False,
            )
        ],
    )
