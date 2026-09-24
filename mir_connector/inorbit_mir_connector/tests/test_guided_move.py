# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Tests for InOrbit routes -> MiR guided_move translation and datatypes."""

from __future__ import annotations

import json
import logging
import math
from types import SimpleNamespace

import pytest
from inorbit_edge_executor.datatypes import (
    MissionDefinition,
    MissionStepPoseWaypoint,
    MissionStepWait,
    Pose,
    RouteSegment,
    RouteSegmentCorridor,
    RouteSegmentTrajectory,
    RouteSegmentTrajectoryNurbsParameters,
)
from inorbit_edge_executor.mission import Mission

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
from inorbit_mir_connector.tests.conftest import (
    FakeMirApi,
    ProgressMirApi,
    build_create_node as _build_create_node,
    mission_with_tasks,
    queue_entry,
    task_status,
    wait_node,
)

ROBOT_ID = "test-robot-01"


def _route_wp(
    x, y, theta=0.0, width=None, label="rwp", complete_task=None, timeout=None, route="route-1"
):
    seg_kwargs = {"routeId": route}
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
        # goal = last run step; its corridor maps to the goal EDGE radius only
        # (arrival tolerance is not corridor-derived)
        assert (gm.goal_x, gm.goal_y) == (3.0, 3.0)
        assert gm.goal_orientation == pytest.approx(90.0)
        assert gm.goal_node_radius is None
        assert gm.goal_edge_radius == 0.5
        # edge = incoming leg; node = min of the adjacent legs
        assert [(w.x, w.y, w.node_radius, w.edge_radius) for w in gm.waypoints] == [
            (1.0, 1.0, 0.5, 0.5),
            (2.0, 2.0, 0.5, 1.0),
        ]
        # nested task-id entry parallel to [*waypoints, goal]
        assert step.action_task_ids == [["t1", "t2", "t3"]]

    def test_no_corridor_leg_has_none_radiuses(self):
        m = _mission([_route_wp(1, 1), _route_wp(2, 2)])
        gm = InOrbitToMirTranslator.translate(m).definition.steps[0].actions[0]
        assert gm.waypoints[0].node_radius is None
        assert gm.goal_node_radius is None

    def test_node_radius_none_when_either_adjacent_leg_has_no_corridor(self):
        m = _mission([_route_wp(1, 1, width=4.0), _route_wp(2, 2), _route_wp(3, 3, width=4.0)])
        gm = InOrbitToMirTranslator.translate(m).definition.steps[0].actions[0]
        assert [(w.node_radius, w.edge_radius) for w in gm.waypoints] == [
            (None, 2.0),  # outgoing leg has no corridor
            (None, None),  # incoming leg has no corridor
        ]

    def test_route_id_change_breaks_run(self):
        m = _mission(
            [
                _route_wp(1, 1, route="r1", complete_task="a1"),
                _route_wp(2, 2, route="r1", complete_task="a2"),
                _route_wp(3, 3, route="r2", complete_task="b1"),
                _route_wp(4, 4, route="r2", complete_task="b2"),
            ]
        )
        step = InOrbitToMirTranslator.translate(m).definition.steps[0]
        assert [type(a) for a in step.actions] == [MirGuidedMove, MirGuidedMove]
        # Each route keeps its own goal (oriented arrival at r1's destination).
        assert (step.actions[0].goal_x, step.actions[1].goal_x) == (2.0, 4.0)
        assert step.action_task_ids == [["a1", "a2"], ["b1", "b2"]]

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

    def test_empty_trajectory_object_is_treated_as_straight_line(self):
        step = _route_wp(1, 1, width=1.0)
        step.routeSegment.trajectory = RouteSegmentTrajectory()
        gm = InOrbitToMirTranslator.translate(_mission([step])).definition.steps[0].actions[0]
        assert isinstance(gm, MirGuidedMove)

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

    def test_plain_waypoint_none_theta_defaults_to_zero_with_warning(self, caplog):
        m = _mission([_plain_wp(1, 1, theta=None)])
        with caplog.at_level(logging.WARNING):
            wp = InOrbitToMirTranslator.translate(m).definition.steps[0].actions[0]
        assert wp.orientation == 0.0
        assert any("theta" in r.message.lower() for r in caplog.records)

    def test_route_properties_dropped_with_warning(self, caplog):
        step = _route_wp(1, 1, width=1.0)
        step.routeSegment.properties = {"maxSpeed": {"value": "0.5"}}
        with caplog.at_level(logging.WARNING):
            InOrbitToMirTranslator.translate(_mission([step, _route_wp(2, 2)]))
        assert any("properties" in r.message.lower() for r in caplog.records)


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


class _Http400Error(Exception):
    """Mimics httpx.HTTPStatusError just enough: carries .response.status_code."""

    def __init__(self, message):
        super().__init__(message)
        self.response = SimpleNamespace(status_code=400)


@pytest.mark.asyncio
async def test_guided_move_400_failure_names_firmware_requirement():
    class FailingApi(FakeMirApi):
        async def add_action_to_mission(self, action_type, mission_id, parameters, priority):
            raise _Http400Error("invalid action type")

    api = FailingApi()
    gm = MirGuidedMove(label="route", goal_x=1.0, goal_y=2.0, goal_orientation=0.0)
    node, ctx = _build_create_node(api, [gm])

    with pytest.raises(RuntimeError, match="3.8.0"):
        await node._execute()


@pytest.mark.asyncio
async def test_non_400_guided_failure_keeps_error_undecorated():
    class FailingApi(FakeMirApi):
        async def add_action_to_mission(self, action_type, mission_id, parameters, priority):
            raise RuntimeError("Connection refused")

    api = FailingApi()
    gm = MirGuidedMove(label="route", goal_x=1.0, goal_y=2.0, goal_orientation=0.0)
    node, ctx = _build_create_node(api, [gm])

    with pytest.raises(RuntimeError) as excinfo:
        await node._execute()
    assert "3.8.0" not in str(excinfo.value)


@pytest.mark.asyncio
async def test_guided_move_rejected_on_v2_firmware_before_create():
    api = FakeMirApi()
    gm = MirGuidedMove(label="route", goal_x=1.0, goal_y=2.0, goal_orientation=0.0)
    node, ctx = _build_create_node(api, [gm], firmware_version="v2")

    with pytest.raises(RuntimeError, match="3.8.0"):
        await node._execute()

    assert api.created == []  # rejected before any robot call


@pytest.mark.asyncio
async def test_failed_create_deletes_orphan_mission():
    class FailingApi(FakeMirApi):
        async def add_action_to_mission(self, action_type, mission_id, parameters, priority):
            raise RuntimeError("boom")

    api = FailingApi()
    node, ctx = _build_create_node(api, [MirWaypoint(label="wp", x=1.0, y=1.0, orientation=0.0)])

    with pytest.raises(RuntimeError):
        await node._execute()

    assert api.deleted_missions == [api.created[0]["guid"]]


def _guided_wait(api, action_task_ids, action_guids):
    """Wait node over a real Mission holding every non-None task id."""
    flat = [
        t for e in action_task_ids for t in (e if isinstance(e, list) else [e]) if t is not None
    ]
    mission = mission_with_tasks(flat)
    node, ctx = wait_node(api, action_task_ids, mission, action_guids, queue_id=7)
    return node, ctx, mission


@pytest.mark.asyncio
async def test_guided_running_marks_intermediates_by_index():
    # current_waypoint_index=3 (waypoint reached, index 0 = start): run steps 0..2
    # completed; the goal task only progresses (it completes with the action).
    api = ProgressMirApi(
        executed=[queue_entry(1, "guid-gm")],
        guided_move={"current_waypoint_index": 3, "guided_move_id": "m-1:0"},
    )
    node, ctx, mission = _guided_wait(api, [["t0", "t1", "t2", "t-goal"]], ["guid-gm"])

    await node._report_progress(7)

    assert [task_status(mission, t) for t in ["t0", "t1", "t2"]] == [(False, True)] * 3
    assert task_status(mission, "t-goal") == (True, False)
    assert ctx.mt.report_tasks.await_count == 1


@pytest.mark.asyncio
async def test_goal_task_not_completed_from_index_while_running():
    # Index at the goal (N+1) but the action has not finished: settling/blocked-path
    # can still abort the move, so the goal task must not be completed positionally.
    api = ProgressMirApi(
        executed=[queue_entry(1, "guid-gm")],
        guided_move={"current_waypoint_index": 2, "guided_move_id": "m-1:0"},
    )
    node, ctx, mission = _guided_wait(api, [["t0", "t-goal"]], ["guid-gm"])

    await node._report_progress(7)

    assert task_status(mission, "t0") == (False, True)
    assert task_status(mission, "t-goal") == (True, False)


@pytest.mark.asyncio
async def test_guided_running_low_index_marks_first_task_in_progress():
    api = ProgressMirApi(
        executed=[queue_entry(1, "guid-gm")],
        guided_move={"current_waypoint_index": 0, "guided_move_id": "m-1:0"},
    )
    node, ctx, mission = _guided_wait(api, [["t0", "t1"]], ["guid-gm"])

    await node._report_progress(7)

    assert task_status(mission, "t0") == (True, False)
    assert task_status(mission, "t1") == (False, False)


@pytest.mark.asyncio
async def test_guided_status_without_matching_id_still_marks_progress(caplog):
    # Empty guided_move_id (a robot that does not echo the parameter): completions are
    # withheld, but the running action still reports the first task in progress, and
    # the degradation is logged once.
    api = ProgressMirApi(
        executed=[queue_entry(1, "guid-gm")],
        guided_move={"current_waypoint_index": 3, "guided_move_id": ""},
    )
    node, ctx, mission = _guided_wait(api, [["t0", "t1", "t2", "t-goal"]], ["guid-gm"])

    with caplog.at_level(logging.WARNING):
        await node._report_progress(7)
        api.guided_move = {"current_waypoint_index": 4, "guided_move_id": ""}
        await node._report_progress(7)

    assert [task_status(mission, t) for t in ["t1", "t2", "t-goal"]] == [(False, False)] * 3
    assert task_status(mission, "t0") == (True, False)
    assert sum("guided_move_id" in r.message for r in caplog.records) == 1


@pytest.mark.asyncio
async def test_guided_second_move_ignores_first_moves_status():
    # Two guided moves in one mission: while the FIRST executes, the status carries its
    # guided_move_id and must not advance the SECOND (queued, not started) run's tasks.
    api = ProgressMirApi(
        executed=[
            queue_entry(1, "guid-a"),
            queue_entry(2, "guid-b", started=False),
        ],
        guided_move={"current_waypoint_index": 3, "guided_move_id": "m-1:0"},
    )
    node, ctx, mission = _guided_wait(
        api, [["a0", "a-goal"], ["b0", "b-goal"]], ["guid-a", "guid-b"]
    )

    await node._report_progress(7)
    await node._report_progress(7)

    assert task_status(mission, "a0") == (False, True)
    assert task_status(mission, "a-goal") == (True, False)
    assert task_status(mission, "b0") == (False, False)
    assert task_status(mission, "b-goal") == (False, False)
    assert api.guided_move_calls == 2  # one GET per poll, not per guided entry


@pytest.mark.asyncio
async def test_guided_finished_completes_all_its_tasks():
    api = ProgressMirApi(executed=[queue_entry(1, "guid-gm", finished=True)])
    node, ctx, mission = _guided_wait(api, [[None, "t1", "t-goal"]], ["guid-gm"])

    await node._report_progress(7)

    assert task_status(mission, "t1") == (False, True)
    assert task_status(mission, "t-goal") == (False, True)
    assert api.guided_move_calls == 0  # finished action: no guided-move poll needed


@pytest.mark.asyncio
async def test_guided_not_polled_while_queued():
    api = ProgressMirApi(executed=[queue_entry(1, "guid-gm", started=False)])
    node, ctx, mission = _guided_wait(api, [["t0", "t1"]], ["guid-gm"])

    await node._report_progress(7)

    assert api.guided_move_calls == 0
    assert task_status(mission, "t0") == (False, False)


@pytest.mark.asyncio
async def test_untracked_guided_run_not_polled():
    api = ProgressMirApi(executed=[queue_entry(1, "guid-gm"), queue_entry(2, "guid-2")])
    node, ctx, mission = _guided_wait(api, [[None, None], "t2"], ["guid-gm", "guid-2"])

    await node._report_progress(7)

    assert api.guided_move_calls == 0
    assert task_status(mission, "t2") == (True, False)


@pytest.mark.asyncio
async def test_guided_poll_failure_degrades_to_mark_at_end(caplog):
    class Boom(ProgressMirApi):
        async def get_guided_move(self):
            raise RuntimeError("boom")

    api = Boom(executed=[queue_entry(1, "guid-gm")])
    node, ctx, mission = _guided_wait(api, [["t0", "t1"]], ["guid-gm"])

    with caplog.at_level(logging.WARNING):
        await node._report_progress(7)  # must not raise
        await node._report_progress(7)

    assert task_status(mission, "t0") == (True, False)  # still in progress, not completed
    assert task_status(mission, "t1") == (False, False)
    # warned once, not once per poll
    assert sum("guided move status" in r.message for r in caplog.records) == 1


@pytest.mark.asyncio
async def test_finish_tasks_flattens_nested_entries():
    api = ProgressMirApi()
    node, ctx, mission = _guided_wait(api, [["t0", None, "t1"], "t2"], ["guid-gm", "guid-2"])

    await node._finish_tasks()

    assert all(task_status(mission, t) == (False, True) for t in ["t0", "t1", "t2"])


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
        {"x": 2.0, "y": 2.0, "node_radius": 0.5, "edge_radius": 1.0},
    ]
    assert params["goal_node_radius"] == 0.5  # fixed arrival tolerance, not corridor
    assert params["goal_edge_radius"] == 0.5
    assert step.action_task_ids == [["t1", "t2", "t3"]]
