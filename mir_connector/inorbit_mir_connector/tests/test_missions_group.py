# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Tests for ``TmpMissionsGroupHandler`` background-task scheduling.

``start()`` routes setup through the one-shot logged-task helper and the garbage-collection loop
through the supervised-task helper, and falls back to bare ``asyncio.create_task`` when neither
is injected.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mir_api():
    api = MagicMock()
    api.get_mission_groups = AsyncMock(return_value=[])
    api.create_mission_group = AsyncMock()
    return api


@pytest.mark.asyncio
async def test_start_routes_through_injected_task_helpers(mir_api):
    """start() routes setup -> spawn_logged_task and GC -> create_supervised_task."""
    from inorbit_mir_connector.src.mir_api.missions_group import TmpMissionsGroupHandler

    created_supervised = []
    spawned_logged = []

    def fake_supervised(name, factory):
        created_supervised.append((name, factory))
        return MagicMock()

    def fake_logged(name, coro):
        spawned_logged.append((name, coro))
        coro.close()  # avoid "coroutine was never awaited" warning
        return MagicMock()

    handler = TmpMissionsGroupHandler(
        mir_api=mir_api,
        create_supervised_task=fake_supervised,
        spawn_logged_task=fake_logged,
    )
    await handler.start()

    # One-shot setup goes through the logged-task helper.
    assert len(spawned_logged) == 1
    setup_name, _setup_coro = spawned_logged[0]
    assert setup_name == "missions-group-setup"

    # Long-lived GC loop goes through the supervised-task helper, passing the bound method as the
    # zero-arg coroutine factory (so it is re-created on each restart).
    assert len(created_supervised) == 1
    gc_name, gc_factory = created_supervised[0]
    assert gc_name == "missions-gc"
    assert gc_factory == handler._missions_garbage_collector


@pytest.mark.asyncio
async def test_start_defaults_to_bare_create_task(mir_api):
    """Without injected helpers, start() falls back to bare asyncio.create_task."""
    from inorbit_mir_connector.src.mir_api.missions_group import TmpMissionsGroupHandler

    handler = TmpMissionsGroupHandler(mir_api=mir_api)
    await handler.start()

    assert len(handler._bg_tasks) == 2
    assert all(isinstance(t, asyncio.Task) for t in handler._bg_tasks)

    await handler.stop()
    assert handler._bg_tasks == []
