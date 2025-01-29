class TranslationException(Exception):
    """
    TranslationException is raised when an InOrbit mission can't be translated
    into the robot/fleet manager specific mission.
    """

    pass


# Exception classes used in the app


class RobotBusyException(Exception):
    """
    RobotBusyException is raised when trying to create a new worker for a robot that is already
    executing a mission
    """

    pass


class TaskPausedException(BaseException):
    """
    TaskPausedException is raised when a worker is executing a behavior tree and it
    is intenionally paused in the middle of its execution.
    """

    pass


class InvalidMissionStateException(Exception):
    """
    InvalidMissionStateException is raised when trying to pause an already paused mission
    or resume a running mission"
    """

    pass


class MissionNotFoundException(Exception):
    """
    MissionNotFoundException is raised when a mission is not found in the database or in the
    workers assigned to the worker pool.
    """

    pass


class BlueboticsMissionRejectedException(Exception):
    """
    BlueboticsMissionRejectedException is raised when a mission is sent to the bluebotics fms
    for execution, but it's rejected.
    """

    pass


class BlueboticsMissionCancelledException(Exception):
    """
    BlueboticsMissionCancelledException is raised when a mission is sent to the bluebotics fms
    for execution, but it's cancelled.
    """

    pass


class BlueboticsMissionStepTranslationException(Exception):
    """
    BlueboticsMissionStepTranslationError is raised when an InOrbit mission can't be translated
    into a bluebotics mission.
    """

    pass
