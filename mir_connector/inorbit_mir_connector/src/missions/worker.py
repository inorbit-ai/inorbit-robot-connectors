import asyncio

from .exceptions import TaskPausedException
from .logger import setup_logger
from .behavior_tree import CANCEL_TASK_PAUSE_MESSAGE, BehaviorTree
from .datatypes import MissionRuntimeOptions
from .datatypes import MissionRuntimeSharedMemory
from .datatypes import MissionWorkerState
from .observable import Observable

logger = setup_logger(name="Worker")


class Worker(Observable):
    """
    Worker is responsible for executing a mission and sending updates through
    Mission Tracking APIs and (in the future) persisting execution state so it can later be resumed
    if the process dies.

    Each worker keeps a state with the current mission step.

    This simple implementation uses "local" workers, in the same process
    """

    def __init__(
        self,
        mission,
        options: MissionRuntimeOptions,
        shared_memory: MissionRuntimeSharedMemory,
    ):
        super().__init__()
        self._mission = mission
        self._options = options
        self._finished = False
        self._paused = False
        self._mt = None
        self._robot = None
        self._robot_api_factory = None
        self._behavior_tree = None
        self._shared_memory = shared_memory

    def id(self):
        return self._mission.id

    def set_behavior_tree(self, tree: BehaviorTree):
        if self._behavior_tree:
            raise Exception("Already initialized")
        self._behavior_tree = tree
        self.subscribe_to_tree_changes()

    def subscribe_to_tree_changes(self):
        # subscribe to changes in *any* node in the tree
        nodes = []
        self._behavior_tree.collect_nodes(nodes)
        for node in nodes:
            node.subscribe(self)

    def set_finished(self, finished):
        self._finished = finished

    def set_paused(self, paused):
        self._paused = paused

    async def notify(self, behavior_tree):
        """Notified when the behavior tree changed. Just propagate the event"""
        await self.notify_observers()

    async def execute(self):
        await self.start()
        self._task = asyncio.create_task(self._behavior_tree.execute())
        try:
            await self._task
            # if an unhandled exception is possible in a task (outside CancelledError),
            # result() allows to handle  the exception when awaiting the task.
            # In this case, it's needed to handle TaskPausedException and avoid marking
            # the task as finished if it was paused in the middle of its execution.
            self._task.result()
            await self.finish()
            self.set_finished(True)
        except TaskPausedException:
            # The task was paused, mission isn't finished
            logger.debug(f"Mission {self._mission.id} paused.")
        try:
            await self.notify_observers()
        except Exception:
            logger.error(f"error notifying observers worker={self.id()}", exc_info=True)

        logger.debug(
            f"finished. State {self._behavior_tree.state}. Last error "
            f" {self._behavior_tree.last_error}"
        )

    async def start(self):
        """
        Prepare for execution. Includes changing the robot to "in mission" state.
        """
        # NOTE(mike) Consider moving this functionality to a behavior tree node
        if self._options.start_mode:
            try:
                await self._robot.add_tag(self._options.start_mode)
            except Exception:
                # The api already prints an error and there is not anything this service can do:
                # the mission gets executed anyway.
                pass

    async def finish(self):
        """
        Performs any cleanup task after the mission ended, including changing robot back to initial
        mode
        """
        # NOTE(mike) Consider moving this functionality to a behavior tree node
        if self._options.end_mode:
            try:
                await self._robot.add_tag(self._options.end_mode)
            except Exception:
                # The api already prints an error and there is not anything this service can do:
                # the mission gets executed anyway.
                pass

    def cancel(self):
        if self._task:
            self._task.cancel()
            return True
        return False

    async def pause(self):
        if self._task:
            self.set_paused(True)
            self._task.cancel(CANCEL_TASK_PAUSE_MESSAGE)

    def serialize(self) -> MissionWorkerState:
        print("In serialize", self._shared_memory)
        return MissionWorkerState(
            mission_id=self._mission.id,
            state=self.dump_object(),
            finished=self._finished,
            robot_id=self.robot_id,
            paused=self._paused,
        )

    def dump_object(self):
        """
        Used for serializing and debugging.
        It dumps a representation of the mission, its behavior tree and the execution status
        in a raw object (dict). This is serialized as an opaque JSON object to persistence DB.
        Some fields may be duplicated in their own columns in the DB for convenience (queries);
        see serialize().
        """
        return {
            "mission": self._mission.model_dump(by_alias=True, exclude_none=True),
            "shared_memory": self._shared_memory.model_dump(by_alias=True, exclude_none=True),
            "options": self._options.model_dump(by_alias=True, exclude_none=True),
            "tree": self._behavior_tree.dump_object(),
            "finished": self._finished,
            "paused": self._paused,
            "robot_id": self.robot_id,
        }

    @property
    def paused(self):
        return self._paused

    @property
    def finished(self):
        return self._finished

    @property
    def robot_id(self):
        return self._mission.robot_id

    @property
    def shared_memory(self):
        return self._shared_memory
