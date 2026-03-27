from setuptools import setup, find_packages

requirements = [
    "httpx>=0.28,<1.0",
    "pytz>=2022.7",
    "pyyaml>=6.0,<7.0",
    "pydantic>=2.11,<3",
    "pydantic-settings>=2.11,<3",
    "inorbit-connector~=2.2.0",
    "psutil>=5.9",
]

setup(
    name="inorbit_neura_connector",
    version="0.1.0",
    description="InOrbit connector for NEURA Robotics (MAV, MAiRA).",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    author="NEURA Robotics",
    license="MIT",
    packages=find_packages(),
    install_requires=requirements,
    extras_require={
        "neurapy_mav": ["neurapy_mav"],
        "grpc": ["grpcio", "grpcio-tools", "nrc_grpc_client"],
    },
    entry_points={
        "console_scripts": [
            "inorbit_neura_connector=inorbit_neura_connector.inorbit_neura_connector:start",
        ]
    },
    python_requires=">=3.10",
    keywords=["connector", "inorbit", "neura", "mav", "maira"],
)
