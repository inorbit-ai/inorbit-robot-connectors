# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

from pathlib import Path


def file_exists(file_path):
    """Checks if a file exists, works for Windows too (pathlib is compatible with both OS)"""
    path = Path(file_path)
    return path.is_file()
