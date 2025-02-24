# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT


from setuptools import find_packages, setup

requirements = [
    "requests>=2.31,<3.0",
    "inorbit-edge[video]>=1.17",
    "inorbit-connector==0.4.0",
    "prometheus-client>=0.14.1",
    "pytz>=2022.7",
    # NOTE: both pyyaml and ruamel.yaml packages are included here. Otherwise, the
    # edge-sdk dependency won't run. Consider migrating edge-sdk yaml dependency
    # to ruamel.yaml or fix the dependency issue and them remove pyyaml from here.
    "pyyaml>=6.0,<6.1",
    "ruamel.yaml>=0.18,<0.19",
    "pydantic>=2.5",
    "psutil==5.9",
    "websocket-client==1.7.0",
    "uuid==1.30",
    "tenacity==9.0.0",
    # Extra missions requirements (not needed once the module is added as a dependency)
    "async-timeout==4.0.3",
    "anyio==3.6.2",
    "autopep8==2.0.0",
    # "certifi==2022.12.7",
    "charset-normalizer==2.1.1",
    "click==8.1.3",
    "dnspython==2.2.1",
    "email-validator==1.3.0",
    "fastapi==0.101.1",
    "h11==0.14.0",
    "httpcore==0.16.2",
    "httptools==0.5.0",
    "httpx==0.24.1",
    "idna==3.4",
    "itsdangerous==2.1.2",
    "Jinja2==3.1.2",
    "MarkupSafe==2.1.1",
    "opentelemetry-api==1.20.0",
    "opentelemetry-sdk==1.20.0",
    "opentelemetry-exporter-prometheus==1.12.0rc1",
    "orjson==3.8.3",
    "pycodestyle==2.10.0",
    # "pydantic==2.3.0",
    # "pydantic-settings==2.0.3",
    "python-dotenv==0.21.0",
    "python-multipart==0.0.5",
    # "PyYAML==5.3.1",
    "rfc3986==1.5.0",
    "six==1.16.0",
    "sniffio==1.3.0",
    "starlette==0.27.0",
    "tomli==2.0.1",
    "typing-extensions==4.7.1",
    "ujson==5.6.0",
    "urllib3==1.26.13",
    "uvicorn==0.20.0",
    "uvloop==0.17.0",
    "watchfiles==0.18.1",
    "websockets==10.4",
    "pytest==7.4.0",
    "pytest-httpx==0.22.0",
    "pytest-asyncio==0.21.1",
    "aiosql==9.0",
    "aiosqlite==0.19.0",
    "bump2version==1.0.1",
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
    description="InOrbit Edge-SDK connector for MiR robots. It polls data from MiR API and sends "
    + "it to InOrbit cloud through the edge-sdk.",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    project_urls={
        "repository": "https://github.com/inorbit-ai/inorbit-robot-connectors/tree/main/mir_connector",  # noqa: E501
        "pypi": "https://pypi.org/project/inorbit-mir-connector",
        "issues": "https://github.com/inorbit-ai/inorbit-robot-connectors/issues",
    },
    author="InOrbit Inc.",
    author_email="support@inorbit.ai",
    license="MIT",
    packages=["inorbit_mir_connector", *find_packages()],
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
            "inorbit-mir100-connector=inorbit_mir_connector.mir100_start:start",
        ]
    },
    python_requires=">=3.7",
    # Do not edit this string manually, always use bump-my-version. See
    # https://github.com/inorbit-ai/inorbit-robot-connectors/tree/main/mir_connector#version-bump
    version="0.2.2",
)
