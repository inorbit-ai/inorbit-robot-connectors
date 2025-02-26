# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

from unittest.mock import AsyncMock, MagicMock

import pytest
from inorbit_mir_connector.src.connector import Mir100Connector
from inorbit_mir_connector.src.missions.behavior_tree import MissionInProgressNode
from inorbit_mir_connector.src.missions.datatypes import (
    MissionDefinition,
    MissionRuntimeOptions,
    MissionStepPoseWaypoint,
    MissionTask,
    Pose,
)
from inorbit_mir_connector.src.missions.mission import Mission
from inorbit_mir_connector.src.missions_exec.behavior_tree import (
    AddMiRMissionActionsNode,
    BehaviorTreeErrorHandler,
    BehaviorTreeSequential,
    CreateMiRMissionNode,
    MirNodeFromStepBuilder,
    QueueMiRMissionNode,
    TaskStartedNode,
    TrackRunningMiRMissionNode,
    WaitUntilMiRMissionIsRunningNode,
)
from inorbit_mir_connector.src.missions_exec.datatypes import (
    MiRInOrbitMission,
    MiRNewMissionData,
    MissionExecuteRequest,
    MissionStepCreateMiRMission,
)
from inorbit_mir_connector.src.missions_exec.executor import MiRMissionsExecutor
from inorbit_mir_connector.src.missions_exec.translator import InOrbitToMirTranslator
from inorbit_mir_connector.src.missions_exec.worker_pool import (
    MirBehaviorTreeBuilderContext,
    MirWorkerPool,
)


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
    assert isinstance(nodes[5], MissionInProgressNode)
    assert isinstance(nodes[6], TrackRunningMiRMissionNode)

    # Verify task IDs are passed correctly
    assert nodes[4].task_id == "first_task"


def test_inorbit_to_mir_translator_single_waypoint():
    """Test translation of a mission with a single waypoint."""

    # Create a simple mission with one waypoint
    mission = Mission(
        id="test-mission-id",
        robot_id="test-robot-id",
        definition=MissionDefinition(
            label="Test Mission",
            steps=[
                MissionStepPoseWaypoint(
                    label="Move to waypoint",
                    timeoutSecs=60.0,
                    completeTask="Move to waypoint",
                    waypoint=Pose(
                        x=10.0,
                        y=5.0,
                        theta=1.57,  # ~90 degrees in radians
                        frameId="map",
                        waypointId="test-waypoint",
                    ),
                )
            ],
            selector={"robot": {"tagIds": ["test-tag"]}},
        ),
    )

    # Translate the mission
    translated_mission = InOrbitToMirTranslator.translate(mission, "temp-group-id", {"retries": 3})

    # Verify the translation
    assert isinstance(translated_mission, MiRInOrbitMission)
    assert len(translated_mission.definition.steps) == 1
    assert isinstance(translated_mission.definition.steps[0], MissionStepCreateMiRMission)

    # Check the MiR mission data
    mir_mission_data = translated_mission.definition.steps[0].mir_mission_data
    assert mir_mission_data.name == "Move to waypoint to Move to waypoint"
    assert mir_mission_data.group_id == "temp-group-id"
    assert len(mir_mission_data.actions) == 1

    # Check the action parameters
    action = mir_mission_data.actions[0]
    assert action.action_type == "move_to_position"

    # Find parameters by id
    params = {param.get("id"): param.get("value") for param in action.parameters if "id" in param}
    assert params["x"] == 10.0
    assert params["y"] == 5.0
    assert params["orientation"] == pytest.approx(90.0, abs=0.1)  # Should be converted to degrees
    assert params["retries"] == 3  # From extra params


def test_inorbit_to_mir_translator_multiple_waypoints():
    """Test translation of a mission with multiple waypoints."""

    # Create a mission with multiple waypoints
    mission = Mission(
        id="test-mission-id",
        robot_id="test-robot-id",
        definition=MissionDefinition(
            label="Test Mission",
            steps=[
                MissionStepPoseWaypoint(
                    label="Move to waypoint 1",
                    timeoutSecs=60.0,
                    completeTask="Task 1",
                    waypoint=Pose(
                        x=10.0,
                        y=5.0,
                        theta=0.0,
                        frameId="map",
                        waypointId="waypoint-1",
                    ),
                ),
                MissionStepPoseWaypoint(
                    label="Move to waypoint 2",
                    timeoutSecs=30.0,
                    completeTask="Task 2",
                    waypoint=Pose(
                        x=15.0,
                        y=8.0,
                        theta=3.14,  # ~180 degrees in radians
                        frameId="map",
                        waypointId="waypoint-2",
                    ),
                ),
            ],
            selector={"robot": {"tagIds": ["test-tag"]}},
        ),
    )

    # Translate the mission
    translated_mission = InOrbitToMirTranslator.translate(mission, "temp-group-id", {})

    # Verify the translation
    assert isinstance(translated_mission, MiRInOrbitMission)
    assert len(translated_mission.definition.steps) == 1  # Should be batched into one step

    step = translated_mission.definition.steps[0]
    assert isinstance(step, MissionStepCreateMiRMission)
    assert step.label == "Batch: Move to waypoint 1 to Move to waypoint 2"
    assert step.timeout_secs == 90.0  # Sum of timeouts
    assert step.complete_task == "Task 2"  # Last task
    assert step.first_task_id == "Task 1"  # First task

    # Check the MiR mission data
    mir_mission_data = step.mir_mission_data
    assert mir_mission_data.name == "Move to waypoint 1 to Move to waypoint 2"
    assert len(mir_mission_data.actions) == 2

    # Check first action
    action1 = mir_mission_data.actions[0]
    assert action1.action_type == "move_to_position"
    params1 = {param.get("id"): param.get("value") for param in action1.parameters if "id" in param}
    assert params1["x"] == 10.0
    assert params1["y"] == 5.0
    assert params1["orientation"] == 0.0

    # Check second action
    action2 = mir_mission_data.actions[1]
    assert action2.action_type == "move_to_position"
    params2 = {param.get("id"): param.get("value") for param in action2.parameters if "id" in param}
    assert params2["x"] == 15.0
    assert params2["y"] == 8.0
    assert params2["orientation"] == pytest.approx(180.0, abs=0.1)  # Should be converted to degrees


@pytest.mark.skip("Doesn't work")
def test_inorbit_to_mir_translator_mixed_steps():
    """Test translation of a mission with mixed step types."""
    # This test needs to be redesigned to use valid step types
    pass
