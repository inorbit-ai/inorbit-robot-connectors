"""
worker_pool

Worker pool implementation. Implements a Pool of workers to be used for mission
execution.
"""

import asyncio

# from .exceptions import RobotBusyException
from .logger import setup_logger
from .behavior_tree import BehaviorTreeBuilderContext
from .behavior_tree import BehaviorTreeErrorHandler
from .behavior_tree import BehaviorTreeSequential
from .behavior_tree import build_tree_from_object
from .behavior_tree import LockRobotNode
from .behavior_tree import MissionAbortedNode
from .behavior_tree import MissionCompletedNode
from .behavior_tree import MissionPausedNode
from .behavior_tree import MissionStartNode
from .behavior_tree import NodeFromStepBuilder
from .behavior_tree import TaskCompletedNode
from .behavior_tree import TaskStartedNode
from .behavior_tree import TimeoutNode
from .behavior_tree import UnlockRobotNode
from .behavior_tree import WaitNode
from .datatypes import MissionRuntimeOptions
from .datatypes import MissionRuntimeSharedMemory
from .datatypes import MissionWorkerState
from .db import WorkerPersistenceDB
from .exceptions import TranslationException
from .inorbit import InOrbitAPI
from .inorbit import MissionStatus
from .inorbit import MissionTrackingMission
from .inorbit import RobotApiFactory
from .mission import Mission
from .worker import Worker

logger = setup_logger(name="WorkerPool")


class WorkerPool:
    """
    Manages and keeps track of workers. It receives missions and executes them
    using Workers. It also persists workers' state and reloads them on restart.

    Different connectors may subclass this class and reimplement with their specifics:

     - create_builder_context(): Creating a subclass of BehaviorTreeBuilderContext
       if necessary, populated with any specific context needed by the connector
       (e.g. an API class).
       Reimplementing prepare_builder_context() is optional; it gets executed later
       after constructing the context.
     - deserialize_mission(): If the Mission class is different from the Mission one used
       by default in the base package, reimplement this. It should only call
       SomeMissionSubclass.model_validate() to deserialize.
     - translate_mission(): An optional step, where a Mission is translated from the
       version received from InOrbit to any other form, as required by the connector.
       Normally, only the definition part of the mission would be changed.
    """

    def __init__(self, api: InOrbitAPI, db: WorkerPersistenceDB):
        if not api:
            raise Exception("Missing InOrbitAPI for WorkerPool initialization")
        self._api = api
        self._db = db
        # Workers, by mission id. Protected by self._mutex
        self._workers = {}
        # No work can be received until this flag is True, set during start().
        self._running = False
        # Lock to protect workers pool state
        self._mutex = asyncio.Lock()

    async def start(self):
        """
        Starts the worker pool. Enables receiving work after this call.
        """
        if self._running:
            return
        self._running = True

        try:
            await self._db.delete_finished_missions()
        except Exception as e:
            logger.error(e)
        # Load state from DB: Retrieve unfinished missions and create workers for them
        serialized_workers = []
        try:
            serialized_workers = await self._db.fetch_all_missions(finished=False, paused=False)
        except Exception as e:
            logger.error("Error loading state from DB. Some missions may not resume", e)

        logger.info(f"Retrieved {len(serialized_workers)} mission workers to resume execution")
        for worker_state in serialized_workers:
            await self.execute_serialized_worker(worker_state)

    async def shutdown(self):
        """
        Stops the worker pool. It's actually not doing anything more than preventing new jobs
        to be submitted.
        """
        self._running = False

    async def notify(self, worker: Worker):
        """Notified when a worker changed its state. Persist it"""
        # TODO(herchu) batch these calls, marking workers as 'dirty': normally, many nodes
        # in the behavior tree are marked as changed (one ends, another starts); or also nodes
        # change and then the worker itself changes (marked as completed). We should not save
        # the object to DB multiple times in these cases.
        if self._running:
            await self.persist(worker)

    def deserialize_mission(self, serialized_mission):
        # Subclasses can change the mission class
        return Mission.model_validate(serialized_mission)

    def build_worker_from_serialized(self, serialized_worker) -> Worker:
        # Note that fields must match the format created by serialize()!
        # First get the fields from
        options = MissionRuntimeOptions.model_validate(serialized_worker.state["options"])
        mission = self.deserialize_mission(serialized_worker.state["mission"])
        shared_memory = MissionRuntimeSharedMemory.model_validate(
            serialized_worker.state["shared_memory"]
        )

        # Make a context for building trees
        context = self.create_builder_context()
        self.prepare_builder_context(context, mission)
        context.shared_memory = shared_memory
        context.options = options
        shared_memory.frozen = False
        tree = build_tree_from_object(context, serialized_worker.state["tree"])
        shared_memory.freeze()

        # Make a context for building trees
        worker = Worker(mission, options, shared_memory)
        worker.set_behavior_tree(tree)
        worker.set_finished(serialized_worker.state["finished"])
        # NOTE (Elvio): This validation was added for backward compatibility when the pause/resume
        # feature was added
        worker.set_paused(serialized_worker.state.get("paused", False))
        return worker

    async def execute_serialized_worker(self, worker_state: MissionWorkerState):
        """
        Executes a serialized worker.
        It creates the worker using FromSerialized() method and executes its behavior tree.
        """
        try:
            worker = self.build_worker_from_serialized(worker_state)
            logger.debug(f"Worker from serialized: {worker}")
            # If the worker was paused, resume it
            if worker.paused:
                # This code executes only when resuming from a paused worker (not resuming from
                # worker that was running at the time the service shut down)
                # We need to un-pause the worker (just a flag), clear any exception handler
                # (so that the pause handlers can execute again) and mark mission as un-paused
                # in Mission Tracking.
                worker.set_paused(False)
                worker._behavior_tree.reset_handlers_execution()
                # Resumes the mission in Mission Tracking
                # NOTE (Elvio): Since the workers have the capability to use the MT API
                # it's not that wrong to call the API here, but consider moving it
                # to another place in the future.
                # The call is here and not in a Node because there's no ResumeNode implemented
                # and also it shouldn't exist
                await worker._mt.start(is_resume=True)
            # Worker is being executed, it should be tracked in memory
            self._workers[worker._mission.id] = worker
            worker.subscribe(self)
            logger.debug(f"Created worker {worker.id} from serialized version")
            # Start executing this mission. The behavior tree will resume from last
            # non-executed node
            asyncio.create_task(worker.execute())
        except Exception as e:
            logger.warning(
                f"Could not build worker {worker_state.mission_id} from serialized version. "
                f"It will NOT resume",
                e,
            )
            try:
                logger.warning(f"Removing mission {worker_state.mission_id}")
                await self._db.delete_mission(worker_state.mission_id)
            except Exception as ex:
                logger.warning(ex)

    def create_builder_context(self) -> BehaviorTreeBuilderContext:
        """
        Creates an empty context for building trees. Subclasses may reimplement and
        return a subclass of BehaviorTreeBuilderContext
        """
        return BehaviorTreeBuilderContext()

    def prepare_builder_context(self, context: BehaviorTreeBuilderContext, mission: Mission):
        """ """
        context.mission = mission
        context.error_context = dict()
        robot_api_factory = RobotApiFactory(self._api)
        context.robot_api_factory = robot_api_factory
        context.robot_api = robot_api_factory.build(mission.robot_id)
        context.mt = MissionTrackingMission(mission, self._api)

    def translate_mission(self, mission: Mission):
        """
        Performs any necessary translation from a mission (from its definition coming
        from InOrbit) to one that the current connector can execute.

        For example, connectors may merge two "visit waypoint" into one "navigate from
        waypoint A to waypoint B" step, if that's how the robot or fleet manager works.

        The resulting MissionDefinition can then include non-standard MissionSteps.

        By default it does nothing; simply returns the same mission.
        """
        return mission

    async def submit_work(
        self,
        mission: Mission,
        options: MissionRuntimeOptions,
        shared_memory: MissionRuntimeSharedMemory = None,
    ):
        if not self._running:
            raise Exception("WorkerPool is not started")

        mission_id = mission.id
        try:
            mission = self.translate_mission(mission)
        except Exception as e:
            logger.exception(e)
            raise TranslationException()

        if not shared_memory:
            shared_memory = MissionRuntimeSharedMemory()

        context = self.create_builder_context()
        self.prepare_builder_context(context, mission)
        context.shared_memory = shared_memory
        context.options = options

        # Create worker, not yet started (it can still be discarded)
        worker = Worker(mission, options, shared_memory)
        try:
            worker.set_behavior_tree(self.build_tree_for_mission(context))
        except Exception as e:
            logger.error(f"Error compiling mission tree: {e}", exc_info=True)
            return {"error": str(e)}

        shared_memory.freeze()
        async with self._mutex:
            current_mission = await self._db.fetch_robot_active_mission(mission.robot_id)
            logger.debug("Robot active mission: %s", current_mission)
            if current_mission is not None:
                raise RobotBusyException()
            self._workers[mission.id] = worker
            # Persist initial state
            await self.persist(worker)
        worker.subscribe(self)
        logger.info(f"Starting execution for mission {mission.id}.")
        asyncio.create_task(worker.execute())
        return {"id": mission_id}  # add status? "executing"

    async def persist(self, worker: Worker):
        try:
            await self._db.save_mission(worker.serialize())
            logger.debug(f"Mission {worker.id()} state persisted")
        except Exception as e:
            logger.error(f"Error persisting worker {worker.id()} state: {str(e)}")

    async def abort_mission(self, mission_id: str) -> bool | dict:
        """
        Aborts running a mission. If there is no worker for the mission, it returns False.

        Args:
            mission_id (str): InOrbit mission ID to abort.

        Return:
            {"id": mission_id, "cancelled": True} if the mission was cancelled,
            {"id": mission_id} if not.
            False, if the mission was not found.
        """
        logger.debug(f"Aborting mission {mission_id}")
        logger.warning("Aborting mission is not implemented")
        if mission_id in self._workers:
            ret = {"id": mission_id}
            # Get the bluebotics Mission ID linked to the inorbit mission id
            # TODO(herchu) Reimplement this, based on
            # - de-serializing mission , and cancel()ing it
            # - letting the behavior tree error handlers (not added yet!) to cancel mission on
            #   bluebotics
            # - if there's no worker for mission_id, attempt to find the bluebotics mission id
            #   anyuway from the last executed step?
            # bluebotics_mission_id = await self._db.get_bluebotics_mission_id(mission_id)
            # if bluebotics_mission_id:
            #   cancelled =
            # await self._bluebotics_api_client.cancel_mission(bluebotics_mission_id)
            #     if cancelled:
            #         ret["cancelled"] = self._workers[mission_id].cancel()
            #         return ret
        return False

    async def get_mission_status(self, mission_id):
        """
        Returns a serialized representation of the status of a mission (of its worker). This uses
        the same serialization methods used for persisting mission states, which must fully
        represent the current status of a mission. It is used only for debugging.
        """
        async with self._mutex:
            if mission_id in self._workers:
                return self._workers[mission_id].dump_object()
            else:
                return None

    def build_tree_for_mission(self, context: BehaviorTreeBuilderContext):

        mission = context.mission
        tree = BehaviorTreeSequential(label=f"mission {mission.id}")
        tree.add_node(MissionStartNode(context, label="mission start"))
        step_builder = NodeFromStepBuilder(context)

        for step, ix in zip(mission.definition.steps, range(len(mission.definition.steps))):
            # TODO build the right kind of behavior node
            try:
                node = step.accept(step_builder)
            except Exception as e:  # TODO
                raise Exception(f"Error building step #{ix} [{step}]: {str(e)}")
            # Before every step, keep robot locked
            tree.add_node(LockRobotNode(context, label="lock robot"))
            if step.timeout_secs is not None and type(node) != WaitNode:
                node = TimeoutNode(step.timeout_secs, node, label=f"timeout for {step.label}")
            if step.complete_task is not None:
                tree.add_node(
                    TaskStartedNode(
                        context,
                        step.complete_task,
                        label=f"report task {step.complete_task} started",
                    )
                )
            if node:
                tree.add_node(node)
            if step.complete_task is not None:
                tree.add_node(
                    TaskCompletedNode(
                        context,
                        step.complete_task,
                        label=f"report task {step.complete_task} completed",
                    )
                )

        tree.add_node(MissionCompletedNode(context, label="mission completed"))
        tree.add_node(UnlockRobotNode(context, label="unlock robot after mission completed"))
        # add error handlers
        on_error = BehaviorTreeSequential(label="error handlers")
        on_error.add_node(
            MissionAbortedNode(context, status=MissionStatus.error, label="mission aborted")
        )
        on_error.add_node(UnlockRobotNode(context, label="unlock robot after mission abort"))
        on_cancel = BehaviorTreeSequential(label="cancel handlers")
        on_cancel.add_node(
            MissionAbortedNode(context, status=MissionStatus.ok, label="mission cancelled")
        )
        on_cancel.add_node(UnlockRobotNode(context, label="unlock robot after mission cancel"))
        on_pause = BehaviorTreeSequential(label="pause handlers")
        on_pause.add_node(MissionPausedNode(context, label="mission paused"))
        tree = BehaviorTreeErrorHandler(
            context, tree, on_error, on_cancel, on_pause, context.error_context, label=tree.label
        )
        return tree
