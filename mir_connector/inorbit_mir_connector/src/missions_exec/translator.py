# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

from inorbit_mir_connector.src.mir_api.mir_api_base import MirApiBaseClass
from inorbit_mir_connector.src.missions.mission import Mission


class InOrbitToMirTranslator:
    """
    A translator class that converts missions from InOrbit format to MiR format.
    """

    @staticmethod
    def translate(inorbit_mission: Mission, mir_api: MirApiBaseClass) -> Mission:
        print("translating beep boop")
        return inorbit_mission
