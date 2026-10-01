# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Tests for `gausium_open_platform_connector.src.api.auth`."""

from __future__ import annotations

import time

import httpx
import pytest

from gausium_open_platform_connector.src.api.auth import REFETCH_MIN_INTERVAL_SECS, TokenAuth


@pytest.fixture()
def fetches() -> list[str]:
    return []


@pytest.fixture()
def auth(fetches: list[str]) -> TokenAuth:
    async def fetch_token() -> str:
        fetches.append(f"tok-{len(fetches) + 1}")
        return fetches[-1]

    return TokenAuth(fetch_token)


@pytest.mark.asyncio
async def test_token_is_fetched_once_and_reused(auth: TokenAuth, fetches: list[str]) -> None:
    # There is no scheduled refresh: only a 401 replaces the token
    assert await auth.token() == "tok-1"
    assert await auth.token() == "tok-1"
    assert len(fetches) == 1


@pytest.mark.asyncio
async def test_refetch_replaces_the_rejected_token(auth: TokenAuth, fetches: list[str]) -> None:
    await auth.token()
    auth._last_fetch -= REFETCH_MIN_INTERVAL_SECS

    assert await auth._refetch("tok-1") is True
    assert await auth.token() == "tok-2"


@pytest.mark.asyncio
async def test_refetch_skips_when_another_caller_already_replaced_it(
    auth: TokenAuth, fetches: list[str]
) -> None:
    await auth.token()
    auth._last_fetch -= REFETCH_MIN_INTERVAL_SECS

    # Concurrent 401s from one stale token must cost a single fetch
    assert await auth._refetch("tok-0") is True
    assert len(fetches) == 1


@pytest.mark.asyncio
async def test_refetch_is_rate_limited(auth: TokenAuth, fetches: list[str]) -> None:
    await auth.token()

    assert await auth._refetch("tok-1") is False
    auth._last_fetch -= REFETCH_MIN_INTERVAL_SECS
    assert await auth._refetch("tok-1") is True
    assert len(fetches) == 2


@pytest.mark.asyncio
async def test_refetch_failure_keeps_the_backoff(fetches: list[str]) -> None:
    async def fetch_token() -> str:
        fetches.append("attempt")
        raise httpx.ConnectError("boom")

    auth = TokenAuth(fetch_token)
    auth._token = "tok-1"
    auth._last_fetch = time.monotonic() - REFETCH_MIN_INTERVAL_SECS

    assert await auth._refetch("tok-1") is False
    assert await auth._refetch("tok-1") is False
    assert len(fetches) == 1
