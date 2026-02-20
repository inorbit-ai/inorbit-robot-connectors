# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest
from inorbit_edge_executor.datatypes import MissionStepRunAction
from inorbit_edge_executor.mission import Mission, MissionDefinition
from inorbit_omron_connector.src.mission.translator import InOrbitToOmronTranslator

def test_translate_invalid_goto_goals_missing_args():
    """Verify that a gotoGoals action with missing arguments raises ValueError."""
    
    step = MissionStepRunAction(runAction={"actionId": "gotoGoals", "arguments": {}})
    
    mission_def = MissionDefinition(steps=[step])
    mission = Mission(id="test-mission", robot_id="robot-1", definition=mission_def)

    with pytest.raises(ValueError) as excinfo:
        InOrbitToOmronTranslator.translate(mission)
    
    assert "gotoGoals action must have argument 'goals'" in str(excinfo.value)

def test_translate_valid_goto_goals_succeeds():
    """Verify that a mission with a valid gotoGoals action succeeds."""
    
    step = MissionStepRunAction(runAction={"actionId": "gotoGoals", "arguments": {"goals": "Goal1,Goal2"}})
    
    mission_def = MissionDefinition(steps=[step])
    mission = Mission(id="test-mission-2", robot_id="robot-1", definition=mission_def)

    # Should succeed
    translated = InOrbitToOmronTranslator.translate(mission)
    assert len(translated.definition.steps) == 1

def test_translate_invalid_goto_goals_only_commas():
    """Verify that a gotoGoals action with only commas raises ValueError."""
    step = MissionStepRunAction(runAction={"actionId": "gotoGoals", "arguments": {"goals": ",,"}})
    
    mission_def = MissionDefinition(steps=[step])
    mission = Mission(id="test-mission-3", robot_id="robot-1", definition=mission_def)

    with pytest.raises(ValueError) as excinfo:
        InOrbitToOmronTranslator.translate(mission)
    
    assert "at least one non-empty goal name" in str(excinfo.value)

def test_translate_goals_trailing_comma():
    """Verify that a trailing comma is ignored."""
    step = MissionStepRunAction(runAction={"actionId": "gotoGoals", "arguments": {"goals": "Goal1,"}})
    
    mission_def = MissionDefinition(steps=[step])
    mission = Mission(id="test-mission-4", robot_id="robot-1", definition=mission_def)

    translated = InOrbitToOmronTranslator.translate(mission)
    # "Goal1," -> ["Goal1"]
    assert len(translated.definition.steps[0].omron_job_details) == 1
    assert translated.definition.steps[0].omron_job_details[0].pickupGoal == "Goal1"
