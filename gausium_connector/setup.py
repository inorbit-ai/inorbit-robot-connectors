#!/usr/bin/env python

# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""The setup script."""
from setuptools import find_packages
from setuptools import setup

with open("README.md") as readme_file:
    readme = readme_file.read()

with open("requirements.txt", "r") as file:
    requirements = file.read().splitlines()

with open("requirements-dev.txt", "r") as file:
    dev_requirements = file.read().splitlines()

extra_requirements = {
    "dev": [*dev_requirements],
    "test": [*dev_requirements],
}

setup(
    name="inorbit_gausium_connector",
    description="InOrbit Edge-SDK connector for Gausium robots.",
    long_description=readme,
    long_description_content_type="text/markdown",
    url="https://github.com/inorbit-ai/inorbit-robot-connectors/tree/main/gausium_connector",
    author="InOrbit Inc.",
    author_email="support@inorbit.ai",
    packages=find_packages(
        include=[
            "inorbit_gausium_connector",
            "inorbit_gausium_connector.*",
        ]
    ),
    install_requires=requirements,
    tests_require=dev_requirements,
    extras_require=extra_requirements,
    classifiers=[
        "Intended Audience :: Other Audience",
        "Programming Language :: Python :: 3",
        "Natural Language :: English",
    ],
    keywords=[
        "connector",
        "edge-sdk",
        "inorbit",
        "robops",
        "inorbit_gausium_connector",
        "Gausium",
    ],
    entry_points={
        "console_scripts": [
            (
                "inorbit_gausium_connector="
                "inorbit_gausium_connector.inorbit_gausium_connector:start"
            ),
        ]
    },
    # Do not edit this string manually, always use bump-my-version.
    # See section "version-bump" in README.md
    version="0.1.0",
    python_requires=">=3.10",
)
