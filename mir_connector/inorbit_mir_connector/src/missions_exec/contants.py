from enum import Enum


class CustomCommands(Enum):
    RUN_MISSION_NOW = "run_mission_now"
    QUEUE_MISSION = "queue_mission"
    ABORT_MISSIONS = "abort_missions"
    SET_STATE = "set_state"
    SET_WAITING_FOR = "set_waiting_for"
    LOCALIZE = "localize"


class SharedMemoryKeys(Enum):
    MIR_MISSION_ID = "mir_mission_id"
    QUEUED_MISSION_ID = "queued_mission_id"
