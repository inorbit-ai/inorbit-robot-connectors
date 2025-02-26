"""
Behavior Trees: Implementation for execution of missions. Mission steps are (loosely) mapped to
nodes in a tree, that often execute in sequence (e.g. BehaviorTreeSequential). There may also
be additional nodes, implicit in the mission definition (e.g. marking the mission as started or
completed in Mission Tracking), or inherent to the execution (an error handler, or a timeout
wrapping another node or step). They are also designed to be extensible to new types of nodes,
including in the future conditionals, iterations, etc. -- there's extensive literature on BTs.

To learn how Mission steps are mapped to which Behavior Tree nodes, see build_tree_for_mission()
and NodeFromStepBuilder.

Behavior Trees must be serializable, since their execution state is persisted in a database in
case the execution service or worker is killed. The mission execution should resume from the point
it was left. (Note that the initial version may have some limitations around this; see comments).

TODOs in this file:
 - Correctly resume timeout/wait nodes, taking into account the time left
 - For Action nodes, read API response and fail if the action was not executed. (Even better: wait
   for completion if the state is 'running')
 - Implement pause/repeat/etc to control execution of a mission. We may need to change the way
   they are implemented (instead of a single task, have tasks be only 1 node?)
"""

import asyncio
import sys
import traceback
from datetime import datetime
from typing import Dict
from typing import List
from typing import Union

from async_timeout import timeout

from .logger import setup_logger
from inorbit_mir_connector.src.missions.exceptions import TaskPausedException
from inorbit_mir_connector.src.missions.datatypes import MissionRuntimeOptions
from inorbit_mir_connector.src.missions.datatypes import MissionRuntimeSharedMemory
from inorbit_mir_connector.src.missions.datatypes import MissionStepPoseWaypoint
from inorbit_mir_connector.src.missions.datatypes import MissionStepRunAction
from inorbit_mir_connector.src.missions.datatypes import MissionStepSetData
from inorbit_mir_connector.src.missions.datatypes import MissionStepWait
from inorbit_mir_connector.src.missions.datatypes import MissionStepWaitUntil
from inorbit_mir_connector.src.missions.datatypes import Target
from inorbit_mir_connector.src.missions.inorbit import MissionStatus
from inorbit_mir_connector.src.missions.inorbit import MissionTrackingMission
from inorbit_mir_connector.src.missions.inorbit import RobotApi
from inorbit_mir_connector.src.missions.inorbit import RobotApiFactory
from inorbit_mir_connector.src.missions.mission import Mission
from inorbit_mir_connector.src.missions.observable import Observable

logger = setup_logger(name="BehaviorTree")

# Shared message between Workers and Behavior Trees
# This message is used in the Behavior Trees to differentiate a cancelled task from a paused task.
CANCEL_TASK_PAUSE_MESSAGE = "pause"

# Tree node states
NODE_STATE_RUNNING = "running"
NODE_STATE_CANCELLED = "cancelled"
NODE_STATE_ERROR = "error"
NODE_STATE_SUCCESS = "success"
NODE_STATE_PAUSED = "paused"

# Arguments that modify behavior
WAYPOINT_DISTANCE_TOLERANCE = "waypointDistanceTolerance"
WAYPOINT_DISTANCE_TOLERANCE_DEFAULT = 1
WAYPOINT_ANGULAR_TOLERANCE = "waypointAngularTolerance"
WAYPOINT_ANGULAR_TOLERANCE_DEFAULT = 1


class BehaviorTreeBuilderContext:
    """
    This object represent all context necessary to build ANY behavior tree node, whether this
    happens during dispatching a mission or de-serializing incomplete missions from storage.
    """

    def __init__(self):
        self._robot_api = None
        self._mt = None
        self._mission = None
        self._error_context = None
        self._robot_api_factory = None
        self._options = None
        self._shared_memory = None
        pass

    @property
    def robot_api(self) -> RobotApi:
        return self._robot_api

    @robot_api.setter
    def robot_api(self, robot_api: RobotApi):
        self._robot_api = robot_api

    @property
    def robot_api_factory(self) -> RobotApiFactory:
        return self._robot_api_factory

    @robot_api_factory.setter
    def robot_api_factory(self, robot_api_factory: RobotApiFactory):
        self._robot_api_factory = robot_api_factory

    @property
    def mt(self) -> MissionTrackingMission:
        return self._mt

    @mt.setter
    def mt(self, mt: MissionTrackingMission):
        self._mt = mt

    @property
    def mission(self) -> Mission:
        return self._mission

    @mission.setter
    def mission(self, mission: Mission):
        self._mission = mission

    @property
    def error_context(self):
        return self._error_context

    @error_context.setter
    def error_context(self, error_context: Dict[str, str]):
        self._error_context = error_context

    # Options come from the svc-mission-dispatcher and are parsed in this service
    # as MissionRuntimeOptions. Used for locks and waypoint's tolerances in
    # behavior trees
    @property
    def options(self):
        return self._options

    @options.setter
    def options(self, options: MissionRuntimeOptions):
        self._options = options

    @property
    def shared_memory(self):
        return self._shared_memory

    @shared_memory.setter
    def shared_memory(self, shared_memory: MissionRuntimeSharedMemory):
        self._shared_memory = shared_memory


class BehaviorTree(Observable):
    """
    Superclass for all Behavior Tree nodes.

    When adding a new subclass, make sure to:
      - call super.__init__() with all **kwargs accepted in this constructor
      - reimplement _execute()
      - implement dump_object() if there is any property that needs to be persisted
      - implement a @classmethod FromObject(), which must receive as args exactly the fields
        added by dump_object(). (See examples in various classes in this file)
      - List the class in accepted_node_types[] list (by the end of this file) to register it
        for (de)serialization
      - Any node type with sub-nodes (non-leaf node) must reimplement collect_nodes to list
        all nodes in the tree
    """

    def __init__(self, label=None, state="", last_error="", start_ts=None):
        super().__init__()
        self.state = state
        self.label = label
        self.last_error = last_error
        self.start_ts = start_ts

    def already_executed(self):
        """
        Determines if this node has already ran. We currently represent it with various states,
        exceptthe initial empty one or "running" or "paused" (meaning it is running, or it
        was persisted while running or it was intentionally paused)
        """
        return self.state and self.state != NODE_STATE_RUNNING and self.state != NODE_STATE_PAUSED

    async def on_pause(self):
        pass

    async def _execute(self):
        pass

    def reset_execution(self):
        """
        Completely reset any "finished" state. This is internally used to mark nodes that already
        executed (e.g. a pause handler) as not executed.

        Most subclasses do not need to reimplement this call; but most importantly,
        BehaviorTreeErrorHandler and BehaviorTreeSequential implement it.
        """
        self.state = ""
        self.start_ts = None
        self.last_error = ""

    def reset_handlers_execution(self):
        """
        Clears any "finished" state on error or pause handlers. This is done so in case we retry
        a mission (after errors) or resume a mission (after pausing), the handlers can be executed
        again and do not ignore calls to execute()

        Most subclasses do not need to reimplement this call; but most importantly,
        BehaviorTreeErrorHandler implements it.
        """
        pass

    async def execute(self):
        if self.already_executed():
            logger.debug(
                f"BT: Called execute on an already executed node; ignoring {self.label} "
                f"state={self.state}"
            )
            # It already ran! ignore
            return
        # Every time a node gets executed for the first time, it stores the start_ts.
        # This happens because some times a Node can start its execution and for
        # some reason it could get paused or interruped, in that case, when the node
        # is about to get executed again the start_ts should remain the same one
        # that was set the first time it tried to execute.
        if not self.start_ts:
            self.start_ts = datetime.now().timestamp()
            await self.notify_observers()
        self.state = NODE_STATE_RUNNING
        try:
            logger.debug(f"Executing node {self.label}")
            await self._execute()
            logger.debug(f"Node {self.label} execution completed")
        except asyncio.CancelledError as e:
            if str(e) == CANCEL_TASK_PAUSE_MESSAGE:
                await self.on_pause()
                self.state = NODE_STATE_PAUSED
                self.last_error = "paused"
            else:
                self.state = NODE_STATE_CANCELLED
                self.last_error = "cancelled"
            await self.notify_observers()
            return
        except Exception as e:
            logger.error(f"Error executing node {self.label}: {str(e)}")
            self.state = NODE_STATE_ERROR
            self.last_error = str(e)
        if self.state == NODE_STATE_RUNNING and not self.state == NODE_STATE_PAUSED:
            self.state = NODE_STATE_SUCCESS
        await self.notify_observers()

    def dump_object(self):
        """
        Serializes this tree. Used for persisting tree states.
        """
        obj = {
            "type": self.__class__.__name__,
            "state": self.state,
        }
        if self.label:
            obj["label"] = self.label
        if self.last_error:
            obj["last_error"] = self.last_error
        if self.start_ts:
            obj["start_ts"] = self.start_ts
        return obj

    def collect_nodes(self, nodes_list: List):  # TODO how to define List[BehaviorTree], same class?
        """
        Collects all tree nodes (including self) to the list nodes.
        Subclasses with children must reimplement this method to recursively visit children nodes.
        """
        nodes_list.append(self)


class BehaviorTreeSequential(BehaviorTree):
    """
    Sequential execution of several nodes (or trees). Normally part of the "steps" sequence of
    a mission, although also used anywhere we need multiple nodes to execute in sequence.
    Failing to execute any node will stop the sequence and mark this tree node also as failed.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.nodes = []

    def add_node(self, node: BehaviorTree):
        self.nodes.append(node)

    async def _execute(self):
        for node in self.nodes:
            # skip nodes that already ran. Necessary when resuming execution of a persisted tree.
            # TODO(herchu) move to a model where we can execute arbitrary nodes keeping track
            # of current one, without requiring to execute everything in a single asyncio task
            if not node.already_executed():
                await node.execute()
                if node.state != NODE_STATE_SUCCESS:
                    self.state = node.state
                    self.last_error = f"{node.label}: {node.last_error}"
                    return
            else:
                logger.debug(
                    f"BTSequential: Skipping execution of already executed node {node.label} "
                    f"state={node.state}"
                )

    def reset_execution(self):
        super().reset_execution()
        for node in self.nodes:
            node.reset_execution()

    def reset_handlers_execution(self):
        super().reset_handlers_execution()
        for node in self.nodes:
            node.reset_handlers_execution()

    def dump_object(self):
        object = super().dump_object()
        object["children"] = [n.dump_object() for n in self.nodes]
        return object

    @classmethod
    def from_object(cls, context: BehaviorTreeBuilderContext, children, **kwargs):
        tree = BehaviorTreeSequential(**kwargs)
        for child in children:
            tree.add_node(build_tree_from_object(context, child))
        return tree

    def collect_nodes(self, nodes_list: List):
        super().collect_nodes(nodes_list)
        for node in self.nodes:
            node.collect_nodes(nodes_list)


class BehaviorTreeErrorHandler(BehaviorTree):
    """
    Wrapper to control error conditions in trees. It allows catching exceptions from a wrapped
    tree, and executing one "error handler" (also a tree) when that exception happens. Those errors
    are caught from exceptions; and the "cancelled" exception is distinguished from any other
    arbitrary exception, given its own error handler tree.
    """

    def __init__(
        self,
        context,
        behavior: BehaviorTree,
        error_handler: BehaviorTree,
        cancelled_handler: BehaviorTree,
        pause_handler: BehaviorTree = None,
        error_context: Dict[str, str] = None,
        # If true, this flag makes the pause handler reset
        # the whole behavior tree and handlers when a pause is triggered.
        reset_execution_on_pause=False,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.behavior = behavior
        self.error_handler = error_handler
        self.cancelled_handler = cancelled_handler
        self.error_context = error_context
        self.pause_handler = pause_handler
        self.reset_execution_on_pause = reset_execution_on_pause

    async def _execute(self):
        await self.behavior.execute()
        if self.behavior.state == NODE_STATE_ERROR:
            if self.error_context is not None:
                self.error_context["last_error"] = self.behavior.last_error
            await self.error_handler.execute()
            self.state = self.error_handler.state
            self.last_error = self.error_handler.last_error
        elif self.behavior.state == NODE_STATE_CANCELLED:
            if self.error_context is not None:
                self.error_context["last_error"] = self.behavior.last_error
            if self.cancelled_handler is not None:
                await self.cancelled_handler.execute()
                self.state = self.cancelled_handler.state
                self.last_error = self.cancelled_handler.last_error
            else:
                self.state = self.behavior.state
                self.last_error = self.behavior.last_error
        elif self.behavior.state == NODE_STATE_PAUSED:
            if self.pause_handler is not None:
                await self.pause_handler.execute()
                # Resets the execution of the behavior tree and handlers
                if self.reset_execution_on_pause:
                    self.behavior.reset_execution()
                    self.reset_handlers_execution()
                # After executing pause_handler, TaskPausedException is raised to stop
                # the execution of worker.execute() and make sure the worker is not marked
                # as finished.
                # Currently running node is serialized and stored in "Paused" state, and it
                # will be executed again when the worker resumes its execution.
                raise TaskPausedException
            else:
                self.state = self.behavior.state
                self.last_error = self.behavior.last_error

    def reset_handlers_execution(self):
        if self.error_handler:
            self.error_handler.reset_execution()
        if self.cancelled_handler:
            self.cancelled_handler.reset_execution()
        if self.pause_handler:
            self.pause_handler.reset_execution()

    def reset_execution(self):
        # No other child nodes, only handlers
        self.reset_handlers_execution()

    def collect_nodes(self, nodes_list: List):
        super().collect_nodes(nodes_list)
        if self.behavior:
            self.behavior.collect_nodes(nodes_list)
        if self.error_handler:
            self.error_handler.collect_nodes(nodes_list)
        if self.cancelled_handler:
            self.cancelled_handler.collect_nodes(nodes_list)
        if self.pause_handler:
            self.pause_handler.collect_nodes(nodes_list)

    def dump_object(self):
        object = super().dump_object()
        object["children"] = [self.behavior.dump_object()]
        object["error_handler"] = self.error_handler.dump_object() if self.error_handler else None
        object["cancelled_handler"] = (
            self.cancelled_handler.dump_object() if self.cancelled_handler else None
        )
        object["pause_handler"] = self.pause_handler.dump_object() if self.pause_handler else None
        object["reset_execution_on_pause"] = self.reset_execution_on_pause
        return object

    @classmethod
    def from_object(
        cls,
        context: BehaviorTreeBuilderContext,
        children,
        error_handler,
        cancelled_handler,
        pause_handler=None,
        reset_execution_on_pause=False,
        **kwargs,
    ):
        behavior_tree: BehaviorTree = build_tree_from_object(context, children[0])
        cancelled_handler_tree: BehaviorTree = (
            build_tree_from_object(context, cancelled_handler) if cancelled_handler else None
        )
        error_handler_tree: BehaviorTree = (
            build_tree_from_object(context, error_handler) if error_handler else None
        )
        error_context = context.error_context
        # NOTE (Elvio): This validation was added for backward compatibility when the pause/resume
        # feature was added
        if pause_handler:
            pause_handler_tree: BehaviorTree = build_tree_from_object(context, pause_handler)
        else:
            pause_handler_tree = None
        tree = BehaviorTreeErrorHandler(
            context,
            behavior_tree,
            error_handler_tree,
            cancelled_handler_tree,
            pause_handler_tree,
            error_context,
            reset_execution_on_pause,
            **kwargs,
        )
        return tree


class TimeoutNode(BehaviorTree):
    """
    Node that wraps the execution of an arbitrary tree, with a given timeout. If this timeout
    triggers before the node is completed, its asyncio.task gets cancelled. The node is marked
    as failed when timing out.
    It is used in any mission step with a "timeoutSecs" property.
    """

    def __init__(self, timeout_seconds, wrapped_bt, **kwargs):
        super().__init__(**kwargs)
        self.timeout_seconds = timeout_seconds
        self.wrapped_bt = wrapped_bt

    async def _execute(self):
        real_timeout = self.start_ts + self.timeout_seconds - datetime.now().timestamp()
        if real_timeout < 0:
            # Timeout time has elapsed, the service could have stopped or restarted.
            raise asyncio.TimeoutError(f"timeout after waiting {self.timeout_seconds} seconds")
        try:
            async with timeout(real_timeout) as cm:
                await self.wrapped_bt.execute()
                if cm.expired:
                    raise asyncio.TimeoutError(
                        f"timeout after waiting {self.timeout_seconds} seconds"
                    )
                if self.wrapped_bt.state == NODE_STATE_ERROR:
                    raise Exception(self.wrapped_bt.last_error)
                if self.wrapped_bt.state == NODE_STATE_CANCELLED:
                    raise asyncio.CancelledError()
        except asyncio.TimeoutError as e:
            raise e

    def collect_nodes(self, nodes_list: List):
        super().collect_nodes(nodes_list)
        self.wrapped_bt.collect_nodes(nodes_list)

    def dump_object(self):
        object = super().dump_object()
        object["wrapped_bt"] = self.wrapped_bt.dump_object()
        object["timeout_seconds"] = self.timeout_seconds
        return object

    @classmethod
    def from_object(cls, context, timeout_seconds, wrapped_bt, **kwargs):
        wrapped_bt = build_tree_from_object(context, wrapped_bt)
        return TimeoutNode(timeout_seconds, wrapped_bt, **kwargs)


class WaitNode(BehaviorTree):
    """
    Node that simply waits for certain number of seconds, and then succeeds.
    It is used for mission steps using timeoutSecs without any other property, meaning they are
    simply waits -- the execution state is always success (unless this node is interrupted by
    some other condition).
    """

    def __init__(self, context, wait_seconds, **kwargs):
        super().__init__(**kwargs)
        self.wait_seconds = wait_seconds

    async def _execute(self):
        wait_time = self.start_ts + self.wait_seconds - datetime.now().timestamp()
        if wait_time < 0:
            # Waiting time has elapsed, the service could have stopped or restarted.
            return
        await asyncio.sleep(wait_time)

    def dump_object(self):
        object = super().dump_object()
        object["wait_seconds"] = self.wait_seconds
        return object

    @classmethod
    def from_object(cls, context, wait_seconds, **kwargs):
        return WaitNode(context, wait_seconds, **kwargs)


class RunActionNode(BehaviorTree):
    """
    Runs an action through REST APIs. This is one of the most common mission steps, running actions
    on the robot executing the mission. It also supports running actions on a different "target"
    (in this first version: another robot).
    """

    def __init__(
        self,
        context: BehaviorTreeBuilderContext,
        action_id,
        arguments,
        target: Target = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.mt = context.mt
        self.action_id = action_id
        self.arguments = arguments
        self.target = target
        if self.target is None:
            self.robot = context.robot_api
        else:
            self.robot = context.robot_api_factory.build(self.target.robot_id)

    async def _execute(self):
        arguments = await self.mt.resolve_arguments(self.arguments)
        resp = await self.robot.execute_action(self.action_id, arguments=arguments)  # noqa: F841
        # TODO track action execution, as done in the app. This JSON response only guarantees
        # the action was *started*.

    async def on_pause(self):
        # TODO (Elvio): Here goes the logic to stop an action when a Mission is paused
        # e.g. Cancel the navigation if a waypoint action is paused.
        logger.debug("TODO: Implement on_pause in RunActionNode")

    def dump_object(self):
        object = super().dump_object()
        object["action_id"] = self.action_id
        object["arguments"] = self.arguments
        if self.target is not None:
            object["target"] = self.target.dump_object()
        return object

    @classmethod
    def from_object(cls, context, action_id, arguments, target=None, **kwargs):
        if target is not None:
            target = Target.from_object(**target)
        return RunActionNode(context, action_id, arguments, target, **kwargs)


class WaitExpressionNode(BehaviorTree):
    """
    Node that evaluates an expression, waiting for its value to be true.
    The expression is evaluated through REST APIs, normally in the same robot that executes the
    mission.
    In this version, it simply re-evaluates the expression every few seconds (not reactive to
    data source changes).
    """

    def __init__(
        self, context: BehaviorTreeBuilderContext, expression: str, target: Target = None, **kwargs
    ):
        super().__init__(**kwargs)
        self.expression = expression
        self.target = target
        if self.target is None:
            self.robot = context.robot_api
        else:
            self.robot = context.robot_api_factory.build(self.target.robot_id)

    async def _execute(self):
        result = False
        logger.debug(f"waiting for expression {self.expression} on {self.robot.robot_id}")
        while not result:
            result = await self.robot.evaluate_expression(self.expression)
            await asyncio.sleep(3)
        logger.debug(f"expression {self.expression} == true")

    def dump_object(self):
        object = super().dump_object()
        object["expression"] = self.expression
        if self.target is not None:
            object["target"] = self.target.dump_object()
        return object

    @classmethod
    def from_object(cls, context, expression, target=None, **kwargs):
        if target is not None:
            target = Target.from_object(**target)
        return WaitExpressionNode(context, expression, target, **kwargs)


class DummyNode(BehaviorTree):
    async def _execute(self):
        pass


class MissionStartNode(BehaviorTree):
    """
    Node that marks missions as started in Mission Tracking. Used at the start of a behavior tree
    execution of a mission.
    """

    def __init__(self, context: BehaviorTreeBuilderContext, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mt = context.mt

    async def _execute(self):
        await self.mt.start()

    # dump_object(): inherited

    @classmethod
    def from_object(cls, context, **kwargs):
        return MissionStartNode(context, **kwargs)


class MissionInProgressNode(BehaviorTree):
    """
    Node that marks missions as in progress in Mission Tracking.
    """

    def __init__(self, context: BehaviorTreeBuilderContext, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mt = context.mt

    async def _execute(self):
        await self.mt.mark_in_progress()

    @classmethod
    def from_object(cls, context, **kwargs):
        return MissionInProgressNode(context, **kwargs)


class MissionCompletedNode(BehaviorTree):
    """
    Node that marks missions as completed in Mission Tracking. Normally used at the end of a normal
    behavior tree execution of a mission.
    """

    def __init__(self, context: BehaviorTreeBuilderContext, *args, **kwargs):
        self.mt = context.mt
        super().__init__(*args, **kwargs)

    async def _execute(self):
        await self.mt.completed()

    # dump_object(): inherited

    @classmethod
    def from_object(cls, context, **kwargs):
        return MissionCompletedNode(context, **kwargs)


class MissionPausedNode(BehaviorTree):
    """
    Node that marks missions as paused in Mission Tracking. Used when a behavior tree node
    execution gets paused.
    """

    def __init__(self, context: BehaviorTreeBuilderContext, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mt = context.mt

    async def _execute(self):
        await self.mt.pause()

    # dump_object(): inherited

    @classmethod
    def from_object(cls, context, **kwargs):
        return MissionPausedNode(context, **kwargs)


class MissionAbortedNode(BehaviorTree):
    """
    Node that marks missions as aborted in Mission Tracking. Normally used in the error handler
    trees.
    """

    def __init__(
        self,
        context: BehaviorTreeBuilderContext,
        status: MissionStatus = MissionStatus.error,
        **kwargs,
    ):
        self.mt = context.mt
        self.error_context = context.error_context
        self.status = status
        super().__init__(**kwargs)

    async def _execute(self):
        await self.mt.add_data(dict(last_error=self.error_context.get("last_error", "unknown")))
        await self.mt.abort(self.status)

    def dump_object(self):
        object = super().dump_object()
        # Note: Enums are not (de)serializable, so we serialize status and str
        object["status"] = str(self.status)
        return object

    @classmethod
    def from_object(cls, context, status, **kwargs):
        # Note: Enums are not (de)serializable, so we serialize status and str
        return MissionAbortedNode(context, MissionStatus(status), **kwargs)


class TaskStartedNode(BehaviorTree):
    """
    Node to mark a Mission Tracking task as completed. Created at the start of mission definition
    steps containing the flag to complete tasks.
    """

    def __init__(self, context: BehaviorTreeBuilderContext, task_id: str, **kwargs):
        self.mt = context.mt
        self.mission = context.mission
        self.task_id = task_id
        super().__init__(**kwargs)

    async def _execute(self):
        self.mission.mark_task_in_progress(self.task_id)
        await self.mt.report_tasks()

    def dump_object(self):
        object = super().dump_object()
        object["task_id"] = self.task_id
        return object

    @classmethod
    def from_object(cls, context, task_id, **kwargs):
        return TaskStartedNode(context, task_id, **kwargs)


class TaskCompletedNode(BehaviorTree):
    """
    Node to mark a Mission Tracking task as completed. Created at the end of mission definition
    steps containing the flag to complete tasks.
    """

    def __init__(self, context: BehaviorTreeBuilderContext, task_id: str, *args, **kwargs):
        self.mt = context.mt
        self.mission = context.mission
        self.task_id = task_id
        super().__init__(*args, **kwargs)

    async def _execute(self):
        self.mission.mark_task_completed(self.task_id)
        await self.mt.report_tasks()

    def dump_object(self):
        object = super().dump_object()
        object["task_id"] = self.task_id
        return object

    @classmethod
    def from_object(cls, context, task_id, **kwargs):
        node = TaskCompletedNode(context, task_id, **kwargs)
        return node


class SetDataNode(BehaviorTree):
    """
    Node to set or append freeform user data to the Mission Tracking mission.
    Directly mapped from setData steps.
    """

    def __init__(
        self, context: BehaviorTreeBuilderContext, data: Dict[str, Union[str, int]], *args, **kwargs
    ):
        self.mt = context.mt
        self.data = data
        super().__init__(*args, **kwargs)

    async def _execute(self):
        await self.mt.add_data(self.data)

    def dump_object(self):
        object = super().dump_object()
        object["data"] = self.data.copy()
        return object

    @classmethod
    def from_object(cls, context, data, **kwargs):
        node = SetDataNode(context, data, **kwargs)
        return node


class LockRobotNode(BehaviorTree):
    """
    Node to lock the robot (and keep it locked; it renews locks if necessary)
    """

    def __init__(self, context: BehaviorTreeBuilderContext, *args, **kwargs):
        self.robot = context.robot_api
        self.use_locks = context.options.use_locks
        super().__init__(*args, **kwargs)

    async def _execute(self):
        # Locks the robot only if it's explicitly sent in mission runtime options
        if self.use_locks:
            logger.debug(f"MissionRuntimeOptions: use_locks = {self.use_locks}. Locking the robot.")
            await self.robot.lock_robot(True)

    @classmethod
    def from_object(cls, context, **kwargs):
        return LockRobotNode(context, **kwargs)


class UnlockRobotNode(BehaviorTree):
    """
    Node to release a robot lock
    """

    def __init__(self, context: BehaviorTreeBuilderContext, *args, **kwargs):
        self.robot = context.robot_api
        self.use_locks = context.options.use_locks
        super().__init__(*args, **kwargs)

    async def _execute(self):
        # Unlocks the robot only if it's explicitly sent in mission runtime options
        if self.use_locks:
            logger.debug(
                f"MissionRuntimeOptions: use_locks = {self.use_locks}. Unlocking the robot."
            )
            await self.robot.unlock_robot(True)

    @classmethod
    def from_object(cls, context, **kwargs):
        return UnlockRobotNode(context, **kwargs)


class NodeFromStepBuilder:
    def __init__(self, context: BehaviorTreeBuilderContext):
        self.context = context
        self.waypoint_distance_tolerance = WAYPOINT_DISTANCE_TOLERANCE_DEFAULT
        self.waypoint_angular_tolerance = WAYPOINT_ANGULAR_TOLERANCE_DEFAULT
        args = context.mission.arguments
        options = context.options
        if options.waypoint_angular_tolerance:
            self.waypoint_angular_tolerance = float(options.waypoint_angular_tolerance)
        if options.waypoint_distance_tolerance:
            self.waypoint_distance_tolerance = float(options.waypoint_distance_tolerance)
        # NOTE(elvio): Waypoint default tolerance can be configured. The default value can be
        # overwritten by account's missions config (coming in MissionRuntimeOptions) or also
        # for a specific mission using its arguments, which takes precedence" over the previous.
        if args is not None:
            if WAYPOINT_DISTANCE_TOLERANCE in args:
                self.waypoint_distance_tolerance = float(args[WAYPOINT_DISTANCE_TOLERANCE])
            if WAYPOINT_ANGULAR_TOLERANCE in args:
                self.waypoint_angular_tolerance = float(args[WAYPOINT_ANGULAR_TOLERANCE])

    def visit_wait(self, step: MissionStepWait):
        return WaitNode(self.context, step.timeout_secs, label=step.label)

    def visit_pose_waypoint(self, step: MissionStepPoseWaypoint):
        raise Exception(
            "Waypoint steps should be handled by a subclass, or translated to a different node type"
        )

    def visit_set_data(self, step: MissionStepSetData):
        # HACK(mike) allow setting the waypoint tolerance using SetData
        # Modifying tolerances with a data step is just a quick hack instead of adding support for
        # defaults for mission arguments.
        # I don't think it's conceptually correct to use data to set waypoint tolerances
        if WAYPOINT_DISTANCE_TOLERANCE in step.data:
            self.waypoint_distance_tolerance = float(step.data[WAYPOINT_DISTANCE_TOLERANCE])
        if WAYPOINT_ANGULAR_TOLERANCE in step.data:
            self.waypoint_angular_tolerance = float(step.data[WAYPOINT_ANGULAR_TOLERANCE])
        # END HACK
        return SetDataNode(self.context, step.data, label=step.label)

    def visit_named_waypoint(self, step):
        raise Exception("Untranslated named waypoint: " + step.waypoint)

    def visit_wait_event(self, step):
        return DummyNode(label=step.label)

    def visit_run_action(self, step: MissionStepRunAction):
        return RunActionNode(
            context=self.context,
            action_id=step.action_id,
            arguments=step.arguments,
            target=step.target,
            label=step.label,
        )

    def visit_wait_until(self, step: MissionStepWaitUntil):
        return WaitExpressionNode(
            context=self.context, expression=step.expression, target=step.target, label=step.label
        )


# List of accepted node types (classes). With register_accepted_node_types(),
# this defines how to build nodes from their type fields (strings)
accepted_node_types = [
    BehaviorTreeSequential,
    BehaviorTreeErrorHandler,
    WaitNode,
    TimeoutNode,
    MissionStartNode,
    MissionCompletedNode,
    MissionAbortedNode,
    TaskStartedNode,
    TaskCompletedNode,
    LockRobotNode,
    UnlockRobotNode,
    MissionPausedNode,
    MissionInProgressNode,
]
tree_node_class_map = {}


def register_accepted_node_types(node_type_classes):
    logger.debug(f"Registering accepted node types: {node_type_classes}")
    for clazz in node_type_classes:
        tree_node_class_map[clazz.__name__] = clazz


register_accepted_node_types(accepted_node_types)


def build_tree_from_object(context: BehaviorTreeBuilderContext, object: dict):
    # print("build_tree_from_object():")
    # if object:
    #     print(object["type"], " keys ->", object.keys())

    node_type = object["type"] if object else None
    if node_type not in tree_node_class_map:
        traceback.print_stack(file=sys.stdout)
        raise Exception(f"Unknown node type from serialized state: {node_type}")

    clazz = tree_node_class_map[node_type]
    del object["type"]
    # print("About to call from_object", clazz, object)
    node = clazz.from_object(context=context, **object)
    return node


class TreeBuilder:
    def build_tree_for_mission(self, context: BehaviorTreeBuilderContext):
        raise Exception("Implemented by subclass")
