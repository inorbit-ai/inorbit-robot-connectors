# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT


from setuptools import setup

requirements = [
    "requests>=2.31,<3.0",
    "httpx>=0.28.1,<0.29.0",
    "inorbit-edge[video]~=1.24",
    "inorbit-connector~=1.4.0",
    "inorbit-edge-executor~=3.2.5",
    "prometheus-client>=0.14.1",
    "pytz>=2022.7",
    # NOTE: both pyyaml and ruamel.yaml packages are included here. Otherwise, the
    # edge-sdk dependency won't run. Consider migrating edge-sdk yaml dependency
    # to ruamel.yaml or fix the dependency issue and them remove pyyaml from here.
    "pyyaml>=6.0,<6.1",
    "ruamel.yaml>=0.18,<0.19",
    "pydantic>=2.11,<3",
    "pydantic-settings>=2.11,<3",
    "psutil==5.9",
    "tenacity>=9.1.2",
]

test_requirements = [
    "pytest>=3",
    "requests_mock==1.11",
    "deepdiff==6.7",
    "pytest-asyncio>=0.23",
    "pytest-httpx~=0.35",
]

dev_requirements = [
    "twine==4.0",
    "build==1.0",
    "bump-my-version~=1.2.4",
    "black",
    "flake8",
]

extra_requirements = {
    "test": [*test_requirements],
    "dev": [*test_requirements, *dev_requirements],
}

setup(
    name="inorbit_mir_connector",
    description="InOrbit Edge-SDK connector for MiR robots. It polls data from MiR API and sends "
    + "it to InOrbit cloud through the edge-sdk.",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    project_urls={
        "repository": "https://github.com/inorbit-ai/inorbit-robot-connectors/tree/main/mir_connector",  # noqa: E501
        "pypi": "https://pypi.org/project/inorbit-mir-connector",
        "issues": "https://github.com/inorbit-ai/inorbit-robot-connectors/issues",
    },
    author="InOrbit Inc.",
    author_email="support@inorbit.ai",
    license="MIT",
    packages=["inorbit_mir_connector"],
    install_requires=requirements,
    tests_require=test_requirements,
    extras_require=extra_requirements,
    classifiers=[
        "Intended Audience :: Other Audience",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Natural Language :: English",
    ],
    keywords=["connector", "edge-sdk", "inorbit", "robops", "mir"],
    entry_points={
        "console_scripts": [
            "inorbit_mir_connector=inorbit_mir_connector.inorbit_mir_connector:start",
        ]
    },
    python_requires=">=3.10",
    # Do not edit this string manually, always use bump-my-version. See
    # https://github.com/inorbit-ai/inorbit-robot-connectors/tree/main/mir_connector#version-bump
    version="1.0.0",
)
