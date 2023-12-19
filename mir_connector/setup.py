# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT


from setuptools import setup

requirements = [
    "requests==2.26.0",
    "inorbit-edge[video]>=1.10.1",
    "prometheus-client>=0.14.1",
    "pytz>=2022.7",
    # NOTE: both pyyaml and ruamel.yaml packages are included here. Otherwise, the
    # edge-sdk dependency won't run. Consider migrating edge-sdk yaml dependency
    # to ruamel.yaml or fix the dependency issue and them remove pyyaml from here.
    "pyyaml>=6.0,<6.1",
    "ruamel.yaml>=0.18,<0.19",
    "pydantic==2.5",
    "psutil==5.9",
]

test_requirements = [
    "pytest>=3",
    "requests_mock==1.11",
    "deepdiff==6.7",
]

dev_requirements = {
    "twine==4.0",
    "build==1.0",
    "bump-my-version==0.15",
    "black",
    "flake8",
}

extra_requirements = {
    "test": [*test_requirements],
    "dev": [*test_requirements, *dev_requirements],
}

setup(
    name="inorbit_mir_connector",
    description="InOrbit Edge-SDK connector for MiR robots. It pools data from MiR API and sends "
    + "it to InOrbit cloud through the edge-sdk.",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    project_urls={
        # TODO(b-Tomas): Check it is the correct one when it is public
        "repository": "https://github.com/inorbit-ai/inorbit-robot-connectors/mir_connector",
        # TODO(b-Tomas): Check it is the correct one when it is public
        "pypi": "https://pypi.org/project/inorbit_mir_connector/",
        "issues": "https://github.com/inorbit-ai/inorbit-robot-connectors/issues",
    },
    author="InOrbit",
    author_email="support@inorbit.ai",
    maintainer="Leandro Pineda, Tomás Badenes, Elvio Aruta",
    maintainer_email="leandro@inorbit.ai, tomas@inorbit.ai, elvio@inorbit.ai",
    license="MIT",
    packages=["inorbit_mir_connector"],
    install_requires=requirements,
    tests_require=test_requirements,
    extras_require=extra_requirements,
    # TODO(Elvio): Add better classifiers
    classifiers=[
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
    ],
    keywords=["connector", "edge-sdk", "inorbit", "robops", "mir"],
    entry_points={
        "console_scripts": [
            "inorbit-mir100-connector=inorbit_mir_connector.mir100_start:start",
        ]
    },
    python_requires=">=3.7",
    # Do not edit this string manually, always use bump-my-version
    # Details in TODO(b-Tomas): add reference to the final documentation file
    version="0.1.0",
)
