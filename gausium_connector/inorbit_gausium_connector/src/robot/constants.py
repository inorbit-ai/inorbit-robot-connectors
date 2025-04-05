# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

from enum import Enum


class WorkType(Enum):
    """Enum to hold possible robot work types."""

    NAVIGATING = "NAVIGATING"
    EXECUTE_TASK = "EXECUTE_TASK"
