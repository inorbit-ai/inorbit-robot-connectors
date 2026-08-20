# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Vendor to cleaning contract normalization, shared by the live key-values and the reports."""

import re

# Vendor `taskState` to the cleaning contract task state
TASK_STATE_MAP = {
    "IDLE": "idle",
    "RUNNING": "cleaning",
    "PAUSED": "paused",
    "OTHER": "unknown",
}

# Vendor cleaning mode to the cleaning contract mode. Only unambiguous modes are mapped:
# intensity variants, carpet cleaning and test modes fall back to "other" instead of being
# guessed into a category.
CLEANING_MODE_MAP = {
    "洗地": "scrub",
    "滚刷洗地": "scrub",
    "尘推": "dust_mop",
    "快速尘推": "dust_mop",
    "低速尘推": "dust_mop",
    "静音推尘": "dust_mop",
    "布刷尘推": "dust_mop",
    "抛光": "polish",
    "深度抛光": "polish",
    "结晶模式": "polish",
    "吸尘": "vacuum",
    "吸风清洁": "vacuum",
    "suction_cleaning": "vacuum",
    "扫地": "sweep",
    "喷雾消毒": "disinfect",
}

# Cleaning modes are reported in Chinese
CLEANING_MODE_LABELS = {
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


def pct(value: float | None) -> float | None:
    """Vendor 0-100 percentage as the contract's 0-1 fraction."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value / 100


def slug(name: str) -> str:
    """Key fragment from a free-form name. e.g. "Main Floor #2" -> "main_floor_2"."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def camel_to_snake(name: str) -> str:
    """e.g. "softSqueegee" -> "soft_squeegee"."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def normalize_task_state(task_state: str | None) -> str:
    """Contract task state for a vendor `taskState`."""
    return TASK_STATE_MAP.get(task_state, "unknown")


def cleaning_mode_keys(mode: str | None) -> dict[str, str]:
    """Cleaning mode published three ways, or nothing when the vendor reported no mode.

    Vendor names carry leading underscores in `cleanModes[]` and `workModes[]` and none in
    reports. e.g. "__洗地" -> {"cleaning_mode": "scrub", "cleaning_mode_raw": "__洗地",
    "cleaning_mode_label": "Wash the floor"}
    """
    if not mode:
        return {}
    name = mode.lstrip("_")
    return {
        "cleaning_mode": CLEANING_MODE_MAP.get(name, "other"),
        "cleaning_mode_raw": mode,
        "cleaning_mode_label": CLEANING_MODE_LABELS.get(name, name),
    }
