# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Top-level package for InOrbit Gausium Open Platform Connector."""

from importlib import metadata

__author__ = """InOrbit Inc."""
__email__ = "support@inorbit.ai"
# Read the installed package version from metadata
try:
    __version__ = metadata.version("gausium-open-platform-connector")
except metadata.PackageNotFoundError:
    __version__ = "unknown"
