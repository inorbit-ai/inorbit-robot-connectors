# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

from enum import Enum


class MissionStatus(Enum):
    """
    Values for InOrbit for mission Status.
    """

    ok = "OK"
    warn = "warn"
    error = "error"


class MissionState(Enum):
    """
    Values for InOrbit for mission States.
    """

    completed = "completed"
    in_progress = "in-progress"
    paused = "paused"
    abandoned = "abandoned"
    starting = "starting"


# Common "Work Mode" translation as provided by Gausium
CLEANING_MODE_TRANSLATION = {
    "尘推": "Dust mop",
    "抛光": "Polish",
    "快速尘推": "High-speed dust mop",
    "深度抛光": "Deep polish",
    "低速尘推": "Low-speed dust mop",
    "结晶模式": "Crystallization mode",
    "地毯清洁": "Carpet cleaning",
    "静音推尘": "Slient dust mopping",
    "喷雾消毒": "Disinfection spray",
    "滚刷洗地": "Roller brush scrubbing",
    "布刷尘推": "Cloth brush dust mopping",
    "轻度清洁": "Light cleaning",
    "中度清洁": "Middle cleaning",
    "重度清洁": "Heavy cleaning",
    "吸风清洁": "Suction cleaning",
    "测试": "Test",
    "扫地": "Sweep the floor",
    "洗地": "Wash the floor",
    "吸尘": "Vacuum",
}
