#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""The setup script."""

from setuptools import find_packages, setup

# Do not edit manually, always use bumpversion (see CONTRIBUTING.rst)
VERSION = "0.0.0"

GITHUB_ORG_URL = "https://github.com/inorbit-ai"
GITHUB_REPO_URL = f"{GITHUB_ORG_URL}/inorbit-robot-connectors"
TEAMCITY_PROJECT_URL = (
    "https://inorbit.teamcity.com/project/"
    "Engineering_Development_DeveloperPortal_Connectors_InorbitInstockConnector"
)

with open("README.md") as file:
    long_description = file.read()

with open("requirements.txt", "r") as file:
    install_requirements = file.read().splitlines()

setup(
    author="InOrbit",
    author_email="support@inorbit.ai",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Natural Language :: English",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    description="InOrbit Connector for the Instock ASRS",
    entry_points={
        "console_scripts": [
            "inorbit-instock-connector=inorbit_instock_connector.main:main",
        ]
    },
    install_requires=install_requirements,
    keywords=["inorbit", "instock", "robops", "robotics"],
    long_description=long_description,
    license="MIT",
    long_description_content_type="text/markdown",
    maintainer="Russell Toris",
    maintainer_email="russell@inorbit.ai",
    name="inorbit-instock-connector",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    platforms=["Linux"],
    project_urls={
        "CI/CD": TEAMCITY_PROJECT_URL,
        "Tracker": f"{GITHUB_REPO_URL}/issues",
        "Contributing": f"{GITHUB_REPO_URL}/blob/v{VERSION}/CONTRIBUTING.md",
        "Code of Conduct": f"{GITHUB_REPO_URL}/blob/v{VERSION}/CODE_OF_CONDUCT.md",
        "Changelog": f"{GITHUB_REPO_URL}/blob/v{VERSION}/CHANGELOG.md",
        "Issue Tracker": f"{GITHUB_REPO_URL}/issues",
        "License": f"{GITHUB_REPO_URL}/blob/v{VERSION}/LICENSE",
        "About": "https://www.inorbit.ai/company",
        "Contact": "https://www.inorbit.ai/contact",
        "Blog": "https://www.inorbit.ai/blog",
        "Twitter": "https://twitter.com/InOrbitAI",
        "LinkedIn": "https://www.linkedin.com/company/inorbitai",
        "GitHub": GITHUB_ORG_URL,
        "Website": "https://www.inorbit.ai/",
        "Source": f"{GITHUB_REPO_URL}/tree/v{VERSION}",
    },
    python_requires=">=3.10, <3.12",
    url=GITHUB_REPO_URL,
    version=VERSION,
)
