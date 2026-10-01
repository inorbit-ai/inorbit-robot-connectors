# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""
Test-wide fixtures.
"""

from __future__ import annotations

import asyncio
import os

import pytest


@pytest.fixture(autouse=True)
def _clean_inorbit_env(monkeypatch):
    """Remove all ``INORBIT_*`` environment variables before each test."""
    for key in list(os.environ):
        if key.startswith("INORBIT_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def _fast_asyncio_sleep(monkeypatch):
    """Short-circuit asyncio.sleep to keep tests fast while still yielding the loop."""

    original_sleep = asyncio.sleep

    async def _sleep_stub(delay, *args, **kwargs):  # type: ignore[unused-argument]
        # Yield control once so background tasks can run, but don't actually delay.
        await original_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", _sleep_stub)
    yield
