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
from inorbit_mir_connector.src.missions_exec.translator import InOrbitToMirTranslator
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


@pytest.mark.skip(reason="Translator not implemented yet")
def test_mission_translator():
    # Create test mission in InOrbit format
    inorbit_mission = Mission(
        id="ac7af1e4-0721-4130-8e1c-80371e16bdf6",
        robot_id="mir100-1",
        definition=MissionDefinitionMiR(
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

    # Create mock MiR API
    mir_api = MagicMock()

    # Translate mission using the translator
    translated = InOrbitToMirTranslator.translate(inorbit_mission, mir_api)

    # Verify the translation maintains essential properties
    assert translated.id == inorbit_mission.id
    assert translated.robot_id == inorbit_mission.robot_id
    assert translated.definition.label == inorbit_mission.definition.label

    # Verify waypoint translation
    original_waypoint = inorbit_mission.definition.steps[0].waypoint
    translated_waypoint = translated.definition.steps[0].waypoint
    assert translated_waypoint.x == original_waypoint.x
    assert translated_waypoint.y == original_waypoint.y
    assert translated_waypoint.theta == original_waypoint.theta
    assert translated_waypoint.frame_id == original_waypoint.frame_id
    assert translated_waypoint.waypointId == original_waypoint.waypointId

    # Verify task translation
    original_task = inorbit_mission.tasks_list[0]
    translated_task = translated.tasks_list[0]
    assert translated_task.task_id == original_task.task_id
    assert translated_task.label == original_task.label
    assert translated_task.in_progress == original_task.in_progress
    assert translated_task.completed == original_task.completed
