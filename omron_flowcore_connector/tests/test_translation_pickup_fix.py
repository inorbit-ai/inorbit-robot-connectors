# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

from inorbit_edge_executor.mission import Mission
from inorbit_edge_executor.datatypes import (
    MissionDefinition,
    MissionStepRunAction,
)
from inorbit_omron_connector.src.mission.translator import InOrbitToOmronTranslator
from inorbit_omron_connector.src.mission.datatypes import MissionStepExecuteOmronJob

def test_translate_starts_with_pickup():
    steps = [
        MissionStepRunAction(runAction={"actionId": "gotoGoals", "arguments": {"goals": "Station_A,Station_B"}})
    ]
    mission_def = MissionDefinition(steps=steps)
    mission = Mission(id="m_pickup_test", robot_id="r1", definition=mission_def)
    
    translated_mission = InOrbitToOmronTranslator.translate(mission)
    
    assert len(translated_mission.definition.steps) == 1
    step = translated_mission.definition.steps[0]
    assert isinstance(step, MissionStepExecuteOmronJob)
    
    # First detail should be a pickup
    assert step.omron_job_details[0].pickupGoal == "Station_A"
    
    # Second detail should be a dropoff
    assert step.omron_job_details[1].dropoffGoal == "Station_B"
