# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import json
from pathlib import Path

import pytest

# Fixtures defined in conftest.py do not require importing

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    """Load a captured API payload from tests/fixtures."""
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def disable_network_calls(httpx_mock):
    # Including httpx_mock will disable network calls on every test that uses httpx
    # Tests that need specific HTTP responses should configure httpx_mock explicitly
    pass


@pytest.fixture
def status_v1() -> dict:
    return load_fixture("B1_status_v1.json")


@pytest.fixture
def status_v2() -> dict:
    return load_fixture("B2_status_v2_S.json")


@pytest.fixture
def task_reports() -> list[dict]:
    return load_fixture("C2_task_reports_v2_90d.json")["robotTaskReports"]


@pytest.fixture
def task_report(task_reports: list[dict]) -> dict:
    return task_reports[0]
