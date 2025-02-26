# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

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
    MiRInOrbitMission,
    MissionExecuteRequest,
    MissionStepCreateMiRMission,
    MiRNewMissionData,
)
from inorbit_mir_connector.src.missions_exec.executor import MiRMissionsExecutor
from inorbit_mir_connector.src.missions_exec.worker_pool import (
    MirBehaviorTreeBuilderContext,
    MirWorkerPool,
)
from inorbit_mir_connector.src.missions_exec.translator import InOrbitToMirTranslator
from inorbit_mir_connector.src.missions_exec.behavior_tree import (
    BehaviorTreeErrorHandler,
    BehaviorTreeSequential,
    MirNodeFromStepBuilder,
)
from inorbit_mir_connector.src.missions_exec.behavior_tree import (
    CreateMiRMissionNode,
    AddMiRMissionActionsNode,
    QueueMiRMissionNode,
    WaitUntilMiRMissionIsRunningNode,
    TaskStartedNode,
    TrackRunningMiRMissionNode,
    TaskCompletedNode,
)
import pytest


@pytest.fixture
def example_request():
    return MissionExecuteRequest(
        missionId="ac7af1e4-0721-4130-8e1c-80371e16bdf6",
        robotId="mir100-1",
        missionDefinition=MissionDefinition(
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
            '{"label":"Test Mission","selector":{"robot":{"tagIds":["f-hPYUnWQMUyMmxT"]}},"steps":[{"label":"Move to waypoint","timeoutSecs":60,"waypoint":{"x":9.892293709504171,"y":5.018981943828619,"theta":0,"frameId":"map","waypointId":"test-waypoint"},"completeTask":"Move to waypoint"}]}',  # noqa: E501
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
    executor = MiRMissionsExecutor(
        inorbit_api=MagicMock(),
        mir_api=MagicMock(),
        temporary_missions_group_id=None,
        waypoint_nav_extra_params={},
        loglevel="DEBUG",
    )
    await executor.start()
    assert isinstance(executor._worker_pool, MirWorkerPool)
    executor._worker_pool.submit_work = AsyncMock()
    await executor.execute_mission(example_request)
    executor._worker_pool.submit_work.assert_called_once()


def test_mission_translator():
    # Create test mission in InOrbit format
    inorbit_mission = Mission(
        id="ac7af1e4-0721-4130-8e1c-80371e16bdf6",
        robot_id="mir100-1",
        definition=MissionDefinition(
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
        arguments={},
        tasks_list=[
            MissionTask(
                taskId="Move to waypoint",
                label="Move to waypoint",
                inProgress=False,
                completed=False,
            )
        ],
    )

    # Test parameters
    temp_missions_group = "test_group"
    nav_params = {"max_speed": 1.0}

    # Translate mission using the translator
    translated = InOrbitToMirTranslator.translate(inorbit_mission, temp_missions_group, nav_params)

    # Verify the translation maintains essential properties
    assert isinstance(translated, MiRInOrbitMission)
    assert translated.id == inorbit_mission.id
    assert translated.robot_id == inorbit_mission.robot_id
    assert translated.definition.label == inorbit_mission.definition.label

    # Verify the MiR mission step was created correctly
    translated_step = translated.definition.steps[0]
    assert isinstance(translated_step, MissionStepCreateMiRMission)
    assert translated_step.label == "Move to waypoint"
    assert translated_step.timeout_secs == 60.0
    assert translated_step.complete_task == "Move to waypoint"
    assert translated_step.first_task_id == "Move to waypoint"
    assert translated_step.last_task_id == "Move to waypoint"

    # Verify MiR mission data
    mir_mission = translated_step.mir_mission_data
    assert mir_mission.name == "Go to test-waypoint"
    assert mir_mission.group_id == temp_missions_group
    assert mir_mission.description == "Navigate to waypoint test-waypoint"

    # Verify MiR action
    action = mir_mission.actions[0]
    assert action.action_type == "move_to_position"
    assert action.priority == 0

    # Verify action parameters include waypoint and extra nav params
    params = action.parameters[0]
    assert params["x"] == 9.892293709504171
    assert params["y"] == 5.018981943828619
    assert params["orientation"] == 0.0  # Converted to degrees
    assert params["max_speed"] == 1.0  # From nav_params

    # Verify tasks list is preserved
    assert len(translated.tasks_list) == 1
    translated_task = translated.tasks_list[0]
    assert translated_task.task_id == "Move to waypoint"
    assert translated_task.label == "Move to waypoint"
    assert translated_task.in_progress is False
    assert translated_task.completed is False


def test_mir_node_from_step_builder():
    # Create mock context
    context = MagicMock(autospec=MirBehaviorTreeBuilderContext)

    # Create a MirNodeFromStepBuilder with the mock context
    builder = MirNodeFromStepBuilder(context)

    # Create a MissionStepCreateMiRMission for testing
    mir_mission_data = MiRNewMissionData(
        name="Test Mission",
        group_id="test_group",
        description="Test Description",
        actions=[
            MiRNewMissionData.MiRNewActionData(
                action_type="move_to_position",
                parameters=[{"x": 1.0, "y": 2.0, "orientation": 90.0}],
                priority=0,
            )
        ],
    )

    mission_step = MissionStepCreateMiRMission(
        label="Test Step",
        timeoutSecs=60.0,
        completeTask="Test Task",
        mir_mission_data=mir_mission_data,
        first_task_id="first_task",
        last_task_id="last_task",
    )

    # Call the visit_create_mir_mission method
    result = builder.visit_create_mir_mission(mission_step)

    # Verify the result is a BehaviorTreeErrorHandler
    assert isinstance(result, BehaviorTreeErrorHandler)

    # Verify the behavior is a BehaviorTreeSequential
    assert isinstance(result.behavior, BehaviorTreeSequential)
    assert result.behavior.label == "Test Step"

    # Verify the sequential behavior tree has the expected nodes
    nodes = result.behavior.nodes
    assert len(nodes) == 7

    # Check each node type in the sequence
    assert isinstance(nodes[0], CreateMiRMissionNode)
    assert isinstance(nodes[1], AddMiRMissionActionsNode)
    assert isinstance(nodes[2], QueueMiRMissionNode)
    assert isinstance(nodes[3], WaitUntilMiRMissionIsRunningNode)
    assert isinstance(nodes[4], TaskStartedNode)
    assert isinstance(nodes[5], TrackRunningMiRMissionNode)
    assert isinstance(nodes[6], TaskCompletedNode)

    # Verify task IDs are passed correctly
    assert nodes[4].task_id == "first_task"
    assert nodes[6].task_id == "last_task"
