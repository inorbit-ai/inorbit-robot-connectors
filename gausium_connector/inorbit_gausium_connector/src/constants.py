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
