# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Custom command definitions for the Gausium Open Platform connector."""

# Standard
from enum import StrEnum


class CustomScripts(StrEnum):
    """InOrbit-facing custom command names (kept identical to v1.x for compatibility)."""

    SUBMIT_TASK = "submit_task"
    TASK_COMMAND = "task_command"
    NAVIGATE = "navigate"


class RemoteTaskCommandType(StrEnum):
    """Vendor remote task command types (``POST v1alpha1/robots/{sn}/commands``)."""

    START_TASK = "START_TASK"
    PAUSE_TASK = "PAUSE_TASK"
    RESUME_TASK = "RESUME_TASK"
    STOP_TASK = "STOP_TASK"


class RemoteNavigationCommandType(StrEnum):
    """Vendor remote navigation command types (``POST v1alpha1/robots/{sn}/commands``)."""

    CROSS_NAVIGATE = "CROSS_NAVIGATE"
    PAUSE_NAVIGATE = "PAUSE_NAVIGATE"
    RESUME_NAVIGATE = "RESUME_NAVIGATE"
    STOP_NAVIGATE = "STOP_NAVIGATE"


class CleaningModes(StrEnum):
    """Cleaning modes accepted by the temp task endpoint (vendor uses Chinese names)."""

    CLEAN = "清洗"
    SWEEP = "清扫"
    DUST = "尘推"
    VACUUM = "吸尘"
