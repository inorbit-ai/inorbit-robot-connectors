# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest
from inorbit_edge_executor.mission import Mission
from inorbit_edge_executor.datatypes import (
    MissionDefinition,
    MissionStepRunAction,
    MissionStepSetData,
)

from inorbit_omron_connector.src.mission.translator import InOrbitToOmronTranslator
from inorbit_omron_connector.src.mission.datatypes import MissionStepExecuteOmronJob

def test_translate_simple_goal():
    steps = [
        MissionStepRunAction(runAction={"actionId": "gotoGoals", "arguments": {"goals": "Goal_A"}})
    ]
    mission_def = MissionDefinition(steps=steps)
    mission = Mission(id="m1", robot_id="r1", definition=mission_def)
    
    translated_mission = InOrbitToOmronTranslator.translate(mission)
    
    assert len(translated_mission.definition.steps) == 1
    step = translated_mission.definition.steps[0]
    assert isinstance(step, MissionStepExecuteOmronJob)
    assert len(step.omron_job_details) == 1
    assert step.omron_job_details[0].pickupGoal == "Goal_A"

    assert step.omron_job_details[0].priority == 10

def test_translate_multiple_goals():
    steps = [
        MissionStepRunAction(runAction={"actionId": "gotoGoals", "arguments": {"goals": "Goal_A,Goal_B"}})
    ]
    mission_def = MissionDefinition(steps=steps)
    mission = Mission(id="m2", robot_id="r1", definition=mission_def)
    
    translated_mission = InOrbitToOmronTranslator.translate(mission)
    
    # Should be grouped into 1 job step
    assert len(translated_mission.definition.steps) == 1
    step = translated_mission.definition.steps[0]
    assert isinstance(step, MissionStepExecuteOmronJob)
    assert len(step.omron_job_details) == 2
    assert step.omron_job_details[0].pickupGoal == "Goal_A"
    assert step.omron_job_details[1].dropoffGoal == "Goal_B"

def test_translate_mixed_steps():
    steps = [
        MissionStepRunAction(runAction={"actionId": "gotoGoals", "arguments": {"goals": "Goal_A"}}),
        MissionStepSetData(label="Set Priority", data={"priority": 5}),
        MissionStepRunAction(runAction={"actionId": "gotoGoals", "arguments": {"goals": "Goal_B"}}),
    ]
    mission_def = MissionDefinition(steps=steps)
    mission = Mission(id="m3", robot_id="r1", definition=mission_def)
    
    translated_mission = InOrbitToOmronTranslator.translate(mission)
    
    # Expect: [Job(Goal_A), SetData, Job(Goal_B)]
    assert len(translated_mission.definition.steps) == 3
    assert isinstance(translated_mission.definition.steps[0], MissionStepExecuteOmronJob)
    assert isinstance(translated_mission.definition.steps[1], MissionStepSetData)
    assert isinstance(translated_mission.definition.steps[2], MissionStepExecuteOmronJob)
    
    assert translated_mission.definition.steps[0].omron_job_details[0].pickupGoal == "Goal_A"
    assert translated_mission.definition.steps[2].omron_job_details[0].pickupGoal == "Goal_B"

def test_translate_invalid_gotogoals():
    steps = [
        # Missing goals argument
        MissionStepRunAction(runAction={"actionId": "gotoGoals", "arguments": {}})
    ]
    mission_def = MissionDefinition(steps=steps)
    mission = Mission(id="m5", robot_id="r1", definition=mission_def)
    
    with pytest.raises(ValueError) as excinfo:
        InOrbitToOmronTranslator.translate(mission)
    
    assert "gotoGoals action must have argument 'goals'" in str(excinfo.value)

def test_translate_set_data_priority():
    steps = [
        MissionStepSetData(label="Set Priority", data={"omron_priority": 5}),
        MissionStepRunAction(runAction={"actionId": "gotoGoals", "arguments": {"goals": "Goal_A"}}),
    ]
    mission_def = MissionDefinition(steps=steps)
    mission = Mission(id="m6", robot_id="r1", definition=mission_def)
    
    translated_mission = InOrbitToOmronTranslator.translate(mission)
    
    # 2 steps: SetData + OmronJob
    assert len(translated_mission.definition.steps) == 2
    
    job_step = translated_mission.definition.steps[1]
    assert isinstance(job_step, MissionStepExecuteOmronJob)
    # Priority should be updated to 5
    assert job_step.omron_job_details[0].priority == 5

def test_translate_timeout_secs():
    steps = [
        MissionStepRunAction(
            runAction={"actionId": "gotoGoals", "arguments": {"goals": "Goal_A"}},
            timeoutSecs=300
        )
    ]
    mission_def = MissionDefinition(steps=steps)
    mission = Mission(id="m7", robot_id="r1", definition=mission_def)
    
    translated_mission = InOrbitToOmronTranslator.translate(mission)
    
    step = translated_mission.definition.steps[0]
    assert step.timeout_secs == 300

def test_translate_multiple_job_steps():
    steps = [
        MissionStepRunAction(runAction={"actionId": "gotoGoals", "arguments": {"goals": "Goal_A"}}),
        MissionStepSetData(label="Set Priority", data={"priority": 5}),
        MissionStepRunAction(runAction={"actionId": "gotoGoals", "arguments": {"goals": "Goal_B"}}),
    ]
    mission_def = MissionDefinition(steps=steps)
    mission = Mission(id="m8", robot_id="r1", definition=mission_def)
    
    translated_mission = InOrbitToOmronTranslator.translate(mission)
    
    assert len(translated_mission.definition.steps) == 3
    step1 = translated_mission.definition.steps[0]
    step2 = translated_mission.definition.steps[2]
    
    assert isinstance(step1, MissionStepExecuteOmronJob)
    assert isinstance(step2, MissionStepExecuteOmronJob)
    
    # job_id should be unique based on index
    assert step1.job_id == "m8_0"
    assert step2.job_id == "m8_2"

def test_translate_with_fleet_robot_id():
    steps = [
        MissionStepRunAction(runAction={"actionId": "gotoGoals", "arguments": {"goals": "Goal_A"}})
    ]
    mission_def = MissionDefinition(steps=steps)
    mission = Mission(id="m9", robot_id="r1", definition=mission_def)
    
    translated_mission = InOrbitToOmronTranslator.translate(mission, fleet_robot_id="AMR_1")
    
    step = translated_mission.definition.steps[0]
    assert step.fleet_robot_id == "AMR_1"
    assert step.robot_id == "r1"

def test_translate_goals_with_whitespace():
    """Verify that goals with whitespace are currently kept (or we can change it to strip them)."""
    steps = [
        MissionStepRunAction(runAction={"actionId": "gotoGoals", "arguments": {"goals": " Goal_A , Goal_B "}})
    ]
    mission_def = MissionDefinition(steps=steps)
    mission = Mission(id="m10", robot_id="r1", definition=mission_def)
    
    translated_mission = InOrbitToOmronTranslator.translate(mission)
    
    step = translated_mission.definition.steps[0]
    # Should strip spaces
    assert step.omron_job_details[0].pickupGoal == "Goal_A"
    assert step.omron_job_details[1].dropoffGoal == "Goal_B"
