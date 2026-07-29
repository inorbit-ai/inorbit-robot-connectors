# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Tests for InOrbit routes -> MiR guided_move translation and datatypes."""

from __future__ import annotations

import json
import logging
import math

import pytest
from inorbit_edge_executor.datatypes import (
    MissionDefinition,
    MissionRuntimeSharedMemory,
    MissionStepPoseWaypoint,
    MissionStepWait,
    Pose,
    RouteSegment,
    RouteSegmentCorridor,
    RouteSegmentTrajectory,
    RouteSegmentTrajectoryNurbsParameters,
)
from inorbit_edge_executor.mission import Mission

from inorbit_mir_connector.src.mission.behavior_tree import (
    CreateMirNativeMissionNode,
    MirBehaviorTreeBuilderContext,
    SharedMemoryKeys,
    WaitForMirMissionCompletionNode,
)
from inorbit_mir_connector.src.mission.datatypes import (
    GuidedMoveWaypoint,
    MirAction,
    MirGuidedMove,
    MirWaypoint,
    MissionStepExecuteMirNativeMission,
)
from inorbit_mir_connector.src.mission.translator import (
    GUIDED_MOVE_MAX_RADIUS,
    InOrbitToMirTranslator,
    _corridor_to_radius,
)

ROBOT_ID = "test-robot-01"


def _route_wp(x, y, theta=0.0, width=None, label="rwp", complete_task=None, timeout=None):
    seg_kwargs = {"routeId": "route-1"}
    if width is not None:
        seg_kwargs["corridor"] = {"width": width}
    kwargs = {
        "waypoint": Pose(x=x, y=y, theta=theta),
        "routeSegment": RouteSegment(**seg_kwargs),
        "label": label,
    }
    if complete_task is not None:
        kwargs["completeTask"] = complete_task
    if timeout is not None:
        kwargs["timeoutSecs"] = timeout
    return MissionStepPoseWaypoint(**kwargs)


def _plain_wp(x, y, theta=0.0, label="wp"):
    return MissionStepPoseWaypoint(waypoint=Pose(x=x, y=y, theta=theta), label=label)


def _mission(steps, label="test"):
    return Mission(
        id="mission-001",
        robot_id=ROBOT_ID,
        definition=MissionDefinition(label=label, steps=steps),
    )


class TestGuidedMoveDatatypes:
    def test_native_step_accepts_guided_move_and_nested_task_ids(self):
        gm = MirGuidedMove(
            label="route",
            goal_x=5.0,
            goal_y=6.0,
            goal_orientation=90.0,
            waypoints=[GuidedMoveWaypoint(x=1.0, y=2.0, node_radius=0.6, edge_radius=0.6)],
            goal_node_radius=0.5,
            goal_edge_radius=0.5,
        )
        step = MissionStepExecuteMirNativeMission(
            label="native",
            actions=[gm],
            robot_id="mir-1",
            action_task_ids=[["t-wp", "t-goal"]],
        )
        assert step.actions[0].waypoints[0].node_radius == 0.6
        assert step.action_task_ids == [["t-wp", "t-goal"]]

    def test_native_step_round_trips_through_serialization(self):
        gm = MirGuidedMove(
            label="route",
            goal_x=5.0,
            goal_y=6.0,
            goal_orientation=90.0,
            waypoints=[GuidedMoveWaypoint(x=1.0, y=2.0)],
        )
        step = MissionStepExecuteMirNativeMission(
            label="native",
            actions=[gm],
            robot_id="mir-1",
            action_task_ids=[[None, "t-goal"]],
        )
        dumped = step.model_dump(mode="json", exclude_none=True, by_alias=True)
        restored = MissionStepExecuteMirNativeMission.model_validate(dumped)
        assert isinstance(restored.actions[0], MirGuidedMove)
        assert restored.actions[0].goal_x == 5.0
        assert restored.actions[0].waypoints[0].edge_radius is None
        assert restored.action_task_ids == [[None, "t-goal"]]


class TestCorridorToRadius:
    def test_symmetric_width_halved(self):
        assert _corridor_to_radius(RouteSegmentCorridor(width=1.2)) == 0.6

    def test_asymmetric_uses_min_side(self):
        c = RouteSegmentCorridor(leftWidth=0.4, rightWidth=0.9)
        assert _corridor_to_radius(c) == 0.4

    def test_clamped_to_mir_max(self):
        assert _corridor_to_radius(RouteSegmentCorridor(width=14.0)) == GUIDED_MOVE_MAX_RADIUS

    def test_none_corridor_is_none(self):
        assert _corridor_to_radius(None) is None


class TestRouteRunGrouping:
    def test_route_run_collapses_into_one_guided_move(self):
        m = _mission(
            [
                _route_wp(1, 1, width=1.0, complete_task="t1"),
                _route_wp(2, 2, width=2.0, complete_task="t2"),
                _route_wp(3, 3, theta=math.radians(90), width=1.0, complete_task="t3"),
            ]
        )
        result = InOrbitToMirTranslator.translate(m)

        assert len(result.definition.steps) == 1
        step = result.definition.steps[0]
        assert len(step.actions) == 1
        gm = step.actions[0]
        assert isinstance(gm, MirGuidedMove)
        # goal = last run step, its corridor maps to goal radiuses
        assert (gm.goal_x, gm.goal_y) == (3.0, 3.0)
        assert gm.goal_orientation == pytest.approx(90.0)
        assert gm.goal_node_radius == 0.5
        assert gm.goal_edge_radius == 0.5
        # intermediates carry their own leg radius (edge INTO the waypoint)
        assert [(w.x, w.y, w.node_radius, w.edge_radius) for w in gm.waypoints] == [
            (1.0, 1.0, 0.5, 0.5),
            (2.0, 2.0, 1.0, 1.0),
        ]
        # nested task-id entry parallel to [*waypoints, goal]
        assert step.action_task_ids == [["t1", "t2", "t3"]]

    def test_no_corridor_leg_has_none_radiuses(self):
        m = _mission([_route_wp(1, 1), _route_wp(2, 2)])
        gm = InOrbitToMirTranslator.translate(m).definition.steps[0].actions[0]
        assert gm.waypoints[0].node_radius is None
        assert gm.goal_node_radius is None

    def test_single_leg_run_has_empty_waypoints(self):
        m = _mission([_route_wp(4, 5, width=1.0)])
        gm = InOrbitToMirTranslator.translate(m).definition.steps[0].actions[0]
        assert gm.waypoints == []
        assert (gm.goal_x, gm.goal_y) == (4.0, 5.0)

    def test_plain_waypoint_breaks_run_but_stays_in_native_group(self):
        m = _mission([_route_wp(1, 1), _route_wp(2, 2), _plain_wp(9, 9)])
        step = InOrbitToMirTranslator.translate(m).definition.steps[0]
        assert len(step.actions) == 2
        assert isinstance(step.actions[0], MirGuidedMove)
        assert isinstance(step.actions[1], MirWaypoint)

    def test_wait_breaks_run(self):
        m = _mission(
            [
                _route_wp(1, 1),
                MissionStepWait(timeoutSecs=5, label="wait"),
                _route_wp(2, 2),
            ]
        )
        step = InOrbitToMirTranslator.translate(m).definition.steps[0]
        assert [type(a) for a in step.actions] == [MirGuidedMove, MirAction, MirGuidedMove]

    def test_route_run_timeout_summed_when_all_bounded(self):
        m = _mission([_route_wp(1, 1, timeout=10), _route_wp(2, 2, timeout=20)])
        step = InOrbitToMirTranslator.translate(m).definition.steps[0]
        assert step.timeout_secs == 30

    def test_route_run_unbounded_when_any_step_unbounded(self):
        m = _mission([_route_wp(1, 1, timeout=10), _route_wp(2, 2)])
        step = InOrbitToMirTranslator.translate(m).definition.steps[0]
        assert step.timeout_secs is None

    def test_nurbs_trajectory_rejected(self):
        nurbs = RouteSegmentTrajectory(
            type="nurbs",
            parameters=RouteSegmentTrajectoryNurbsParameters(
                degree=2,
                knotVector=[0, 0, 0, 1, 1, 1],
                controlPoints=[{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 1.0}, {"x": 2.0, "y": 0.0}],
            ),
        )
        step = MissionStepPoseWaypoint(
            waypoint=Pose(x=1, y=1, theta=0),
            routeSegment=RouteSegment(routeId="route-1", trajectory=nurbs),
            label="nurbs-wp",
        )
        with pytest.raises(ValueError, match="(?i)nurbs"):
            InOrbitToMirTranslator.translate(_mission([step]))

    def test_intermediate_theta_dropped_with_warning(self, caplog):
        m = _mission(
            [
                _route_wp(1, 1, theta=math.radians(45)),
                _route_wp(2, 2, theta=math.radians(90)),
            ]
        )
        with caplog.at_level(logging.WARNING):
            gm = InOrbitToMirTranslator.translate(m).definition.steps[0].actions[0]
        assert not hasattr(gm.waypoints[0], "orientation")
        assert any("theta" in r.message.lower() for r in caplog.records)

    def test_intermediate_zero_theta_dropped_without_warning(self, caplog):
        # Dispatched waypoints virtually always carry theta (usually 0.0); warning
        # only when it is nonzero, or every multi-leg route would log noise.
        m = _mission([_route_wp(1, 1, theta=0.0), _route_wp(2, 2, theta=0.0)])
        with caplog.at_level(logging.WARNING):
            InOrbitToMirTranslator.translate(m)
        assert not any("theta" in r.message.lower() for r in caplog.records)

    def test_none_theta_defaults_to_zero_orientation(self):
        # Pose.theta is Optional; a None goal theta must not crash translation.
        m = _mission([_route_wp(1, 1, theta=None), _route_wp(2, 2, theta=None)])
        gm = InOrbitToMirTranslator.translate(m).definition.steps[0].actions[0]
        assert gm.goal_orientation == 0.0

    def test_plain_waypoint_none_theta_defaults_to_zero_orientation(self):
        m = _mission([_plain_wp(1, 1, theta=None)])
        wp = InOrbitToMirTranslator.translate(m).definition.steps[0].actions[0]
        assert wp.orientation == 0.0

    def test_route_properties_dropped_with_warning(self, caplog):
        step = _route_wp(1, 1, width=1.0)
        step.routeSegment.properties = {"maxSpeed": {"value": "0.5"}}
        with caplog.at_level(logging.WARNING):
            InOrbitToMirTranslator.translate(_mission([step, _route_wp(2, 2)]))
        assert any("properties" in r.message.lower() for r in caplog.records)


class FakeMirApi:
    def __init__(self, queue_id=42):
        self.created = []
        self.actions = []
        self.queued = []
        self._queue_id = queue_id

    async def create_mission(self, group_id, name, guid, description):
        self.created.append({"group_id": group_id, "guid": guid})

    async def add_action_to_mission(self, action_type, mission_id, parameters, priority):
        self.actions.append(
            {"action_type": action_type, "parameters": parameters, "priority": priority}
        )
        return {"guid": f"action-guid-{priority}"}

    async def queue_mission(self, mission_guid):
        self.queued.append(mission_guid)
        return {"id": self._queue_id}

    async def get_position_docking_offsets(self, position_guid):
        return []


def _build_create_node(api, actions, action_task_ids=None):
    ctx = MirBehaviorTreeBuilderContext(
        mir_api=api,
        missions_group_id="grp-1",
        firmware_version="v3",
        connector_type="mir",
    )
    ctx.shared_memory = MissionRuntimeSharedMemory()
    step = MissionStepExecuteMirNativeMission(
        label="native",
        actions=actions,
        robot_id="mir-1",
        action_task_ids=action_task_ids or [],
    )
    node = CreateMirNativeMissionNode(ctx, step)
    ctx.shared_memory.freeze()
    return node, ctx


def _params_by_id(recorded_action):
    return {p["id"]: p["value"] for p in recorded_action["parameters"]}


@pytest.mark.asyncio
async def test_guided_move_action_parameters():
    api = FakeMirApi()
    gm = MirGuidedMove(
        label="route",
        goal_x=5.0,
        goal_y=6.0,
        goal_orientation=90.0,
        waypoints=[
            GuidedMoveWaypoint(x=1.0, y=2.0, node_radius=0.6, edge_radius=0.6),
            GuidedMoveWaypoint(x=3.0, y=4.0),
        ],
        goal_node_radius=0.5,
        goal_edge_radius=0.5,
    )
    node, ctx = _build_create_node(api, [gm])

    await node._execute()

    assert [a["action_type"] for a in api.actions] == ["guided_move"]
    params = _params_by_id(api.actions[0])
    assert params["x"] == 5.0
    assert params["y"] == 6.0
    assert params["orientation"] == 90.0
    assert params["goal_node_radius"] == 0.5
    assert params["goal_edge_radius"] == 0.5
    assert params["blocked_path_timeout"] == 60.0
    assert json.loads(params["waypoints"]) == [
        {"x": 1.0, "y": 2.0, "node_radius": 0.6, "edge_radius": 0.6},
        # No corridor on the leg: line-following (edge 0) with the default node rounding.
        {"x": 3.0, "y": 4.0, "node_radius": 0.3, "edge_radius": 0.0},
    ]
    # Center-based deviation always (footprint mode rejects narrow corridors);
    # identity is <mission guid>:<action index>.
    assert params["keep_footprint_within_inflation"] is False
    assert params["guided_move_id"] == f"{api.created[0]['guid']}:0"
    # The robot rejects the action unless every schema parameter is present.
    assert params["position"] is None
    assert params["start_node_radius"] == 0.5
    assert params["enable_node_resource_handling"] is False
    assert params["assigned_waypoint_index"] is None


@pytest.mark.asyncio
async def test_guided_move_without_corridor_sends_schema_defaults():
    api = FakeMirApi()
    gm = MirGuidedMove(label="route", goal_x=1.0, goal_y=2.0, goal_orientation=0.0)
    node, ctx = _build_create_node(api, [gm])

    await node._execute()

    params = _params_by_id(api.actions[0])
    # No corridor: goal arrival keeps the schema-default node radius, but the edge is
    # line-following (all params must still be present or the robot rejects the action).
    assert params["goal_node_radius"] == 0.5
    assert params["goal_edge_radius"] == 0.0
    assert params["keep_footprint_within_inflation"] is False
    assert json.loads(params["waypoints"]) == []


@pytest.mark.asyncio
async def test_guided_move_mixes_with_other_actions_in_order():
    api = FakeMirApi()
    gm = MirGuidedMove(label="route", goal_x=1.0, goal_y=2.0, goal_orientation=0.0)
    node, ctx = _build_create_node(
        api,
        [
            gm,
            MirWaypoint(label="wp", x=9.0, y=9.0, orientation=0.0),
        ],
    )

    await node._execute()

    assert [a["action_type"] for a in api.actions] == ["guided_move", "move_to_position"]
    assert [a["priority"] for a in api.actions] == [1, 2]


@pytest.mark.asyncio
async def test_guided_move_failure_names_firmware_requirement():
    class FailingApi(FakeMirApi):
        async def add_action_to_mission(self, action_type, mission_id, parameters, priority):
            raise RuntimeError("invalid action type")

    api = FailingApi()
    gm = MirGuidedMove(label="route", goal_x=1.0, goal_y=2.0, goal_orientation=0.0)
    node, ctx = _build_create_node(api, [gm])

    with pytest.raises(RuntimeError, match="3.8.0"):
        await node._execute()


class FakeTrackingMirApi:
    """Drives WaitForMirMissionCompletionNode._report_progress: queue actions +
    per-action detail + guided move status."""

    def __init__(self):
        # queue action int id -> {"action_id": guid, "finished": ts_or_None}
        self.queue_actions: dict = {}
        self.guided_move: dict | None = None
        self.guided_move_calls = 0

    async def get_mission_queue_actions(self, queue_id):
        return [{"id": i} for i in self.queue_actions]

    async def get_mission_queue_action(self, queue_id, action_int_id):
        return {"id": action_int_id, **self.queue_actions[action_int_id]}

    async def get_guided_move(self):
        self.guided_move_calls += 1
        return self.guided_move


class FakeMission:
    def __init__(self):
        self.completed: list[str] = []
        self.in_progress: list[str] = []

    def mark_task_completed(self, task_id):
        self.completed.append(task_id)

    def mark_task_in_progress(self, task_id):
        self.in_progress.append(task_id)


class FakeMT:
    def __init__(self):
        self.reports = 0

    async def report_tasks(self):
        self.reports += 1


def _build_wait_node(api, action_task_ids, action_guids):
    ctx = MirBehaviorTreeBuilderContext(
        mir_api=api,
        missions_group_id="grp-1",
        firmware_version="v3",
        connector_type="mir",
    )
    ctx.shared_memory = MissionRuntimeSharedMemory()
    ctx.mission = FakeMission()
    ctx.mt = FakeMT()
    node = WaitForMirMissionCompletionNode(ctx, action_task_ids=action_task_ids)
    ctx.shared_memory.add(SharedMemoryKeys.MIR_ACTION_GUIDS, action_guids)
    ctx.shared_memory.add(SharedMemoryKeys.MIR_QUEUE_ID, 7)
    ctx.shared_memory.add(SharedMemoryKeys.MIR_MISSION_GUID, "m-1")
    ctx.shared_memory.freeze()
    return node, ctx


@pytest.mark.asyncio
async def test_guided_running_marks_intermediates_by_index():
    api = FakeTrackingMirApi()
    api.queue_actions = {1: {"action_id": "guid-gm", "finished": None}}
    # current_waypoint_index=3 (waypoint reached, index 0 = start): run steps 0..2 completed
    api.guided_move = {"current_waypoint_index": 3, "guided_move_id": "m-1:0"}
    node, ctx = _build_wait_node(api, [["t0", "t1", "t2", "t-goal"]], ["guid-gm"])

    await node._report_progress(7)

    assert ctx.mission.completed == ["t0", "t1", "t2"]
    assert ctx.mt.reports == 1


@pytest.mark.asyncio
async def test_guided_running_low_index_marks_first_task_in_progress():
    api = FakeTrackingMirApi()
    api.queue_actions = {1: {"action_id": "guid-gm", "finished": None}}
    api.guided_move = {"current_waypoint_index": 0, "guided_move_id": "m-1:0"}
    node, ctx = _build_wait_node(api, [["t0", "t1"]], ["guid-gm"])

    await node._report_progress(7)

    assert ctx.mission.completed == []
    assert ctx.mission.in_progress == ["t0"]


@pytest.mark.asyncio
async def test_guided_status_without_matching_id_is_ignored():
    api = FakeTrackingMirApi()
    api.queue_actions = {1: {"action_id": "guid-gm", "finished": None}}
    # Empty guided_move_id (as an idle robot reports): not our move, ignore it.
    api.guided_move = {"current_waypoint_index": 3, "guided_move_id": ""}
    node, ctx = _build_wait_node(api, [["t0", "t1", "t2", "t-goal"]], ["guid-gm"])

    await node._report_progress(7)
    api.guided_move = {"current_waypoint_index": 4, "guided_move_id": ""}
    await node._report_progress(7)

    assert ctx.mission.completed == []
    assert ctx.mission.in_progress == []


@pytest.mark.asyncio
async def test_guided_second_move_ignores_first_moves_status():
    # Two guided moves queued in one mission: while the FIRST runs, the status
    # carries its guided_move_id and must not advance the SECOND run's tasks.
    api = FakeTrackingMirApi()
    api.queue_actions = {
        1: {"action_id": "guid-a", "finished": None},
        2: {"action_id": "guid-b", "finished": None},
    }
    api.guided_move = {"current_waypoint_index": 3, "guided_move_id": "m-1:0"}
    node, ctx = _build_wait_node(api, [["a0", "a1"], ["b0", "b1"]], ["guid-a", "guid-b"])

    await node._report_progress(7)
    api.guided_move = {"current_waypoint_index": 4, "guided_move_id": "m-1:0"}
    await node._report_progress(7)

    assert "b0" not in ctx.mission.completed and "b1" not in ctx.mission.completed
    assert ctx.mission.in_progress == []  # unmatched run reports nothing mid-flight
    assert sorted(set(ctx.mission.completed)) == ["a0", "a1"]


@pytest.mark.asyncio
async def test_guided_finished_completes_all_its_tasks():
    api = FakeTrackingMirApi()
    api.queue_actions = {1: {"action_id": "guid-gm", "finished": "2026-07-22T10:00:00"}}
    node, ctx = _build_wait_node(api, [[None, "t1", "t-goal"]], ["guid-gm"])

    await node._report_progress(7)

    assert sorted(ctx.mission.completed) == ["t-goal", "t1"]
    assert api.guided_move_calls == 0  # finished action: no guided-move poll needed


@pytest.mark.asyncio
async def test_guided_poll_failure_degrades_to_mark_at_end():
    class Boom(FakeTrackingMirApi):
        async def get_guided_move(self):
            raise RuntimeError("boom")

    api = Boom()
    api.queue_actions = {1: {"action_id": "guid-gm", "finished": None}}
    node, ctx = _build_wait_node(api, [["t0", "t1"]], ["guid-gm"])

    await node._report_progress(7)  # must not raise

    assert ctx.mission.completed == []


@pytest.mark.asyncio
async def test_finish_tasks_flattens_nested_entries():
    api = FakeTrackingMirApi()
    node, ctx = _build_wait_node(api, [["t0", None, "t1"], "t2"], ["guid-gm", "guid-2"])

    await node._finish_tasks()

    assert sorted(ctx.mission.completed) == ["t0", "t1", "t2"]


@pytest.mark.asyncio
async def test_translated_route_run_posts_one_guided_move_action():
    """Integration: translator output fed straight into CreateMirNativeMissionNode."""
    m = _mission(
        [
            _route_wp(1, 1, width=1.0, complete_task="t1"),
            _route_wp(2, 2, width=2.0, complete_task="t2"),
            _route_wp(3, 3, theta=math.radians(90), width=1.0, complete_task="t3"),
        ]
    )
    step = InOrbitToMirTranslator.translate(m).definition.steps[0]
    assert isinstance(step, MissionStepExecuteMirNativeMission)

    api = FakeMirApi()
    node, ctx = _build_create_node(api, step.actions, step.action_task_ids)

    await node._execute()

    assert [a["action_type"] for a in api.actions] == ["guided_move"]
    params = _params_by_id(api.actions[0])
    assert params["x"] == 3.0
    assert params["y"] == 3.0
    assert params["orientation"] == pytest.approx(90.0)
    assert json.loads(params["waypoints"]) == [
        {"x": 1.0, "y": 1.0, "node_radius": 0.5, "edge_radius": 0.5},
        {"x": 2.0, "y": 2.0, "node_radius": 1.0, "edge_radius": 1.0},
    ]
    assert params["goal_node_radius"] == 0.5
    assert params["goal_edge_radius"] == 0.5
    assert step.action_task_ids == [["t1", "t2", "t3"]]
