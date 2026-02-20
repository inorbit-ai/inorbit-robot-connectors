# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import importlib.metadata

try:
    __version__ = importlib.metadata.version("inorbit-omron-connector")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0"
