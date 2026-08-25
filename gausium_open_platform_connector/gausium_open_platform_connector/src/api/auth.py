# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Bearer token authentication for httpx clients."""

# Standard
import asyncio
import logging
import time
from collections.abc import AsyncGenerator, Awaitable, Callable

# Third-party
import httpx

# Minimum spacing between token fetches, so a 401 that a new token cannot fix
# (rejected credentials, quota) does not fetch one per request
REFETCH_MIN_INTERVAL_SECS = 60.0


class TokenAuth(httpx.Auth):
    """Bearer auth that replaces its token when the server rejects it.

    There is no scheduled refresh: the 401 is the server's own verdict on the token, and
    an expiry the client computes can only ever disagree with it. ``fetch_token`` is an
    awaitable returning the access token.

    TODO: this is vendor-agnostic; move it into inorbit-connector so every connector with a
    bearer-token API gets 401 recovery.
    """

    def __init__(self, fetch_token: Callable[[], Awaitable[str]]) -> None:
        """Initialize the auth flow.

        Args:
            fetch_token: Coroutine function returning an access token.
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self._fetch_token = fetch_token
        self._token: str | None = None
        self._last_fetch: float = 0.0
        self._lock = asyncio.Lock()

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        """Send the request with a Bearer header, retrying once with a fresh token."""
        token = await self.token()
        request.headers["Authorization"] = f"Bearer {token}"
        response = yield request
        if response.status_code == httpx.codes.UNAUTHORIZED and await self._refetch(token):
            request.headers["Authorization"] = f"Bearer {self._token}"
            yield request

    async def token(self) -> str:
        """Return the cached token, fetching one on first use."""
        if self._token is not None:
            return self._token
        # Concurrent callers (the two batch polls run gathered) must not both fetch
        async with self._lock:
            if self._token is None:
                await self._fetch()
        return self._token

    async def _refetch(self, rejected: str) -> bool:
        """Replace the token that was rejected; ``False`` if the caller should give up."""
        async with self._lock:
            if self._token != rejected:
                return True
            if time.monotonic() - self._last_fetch < REFETCH_MIN_INTERVAL_SECS:
                return False
            self.logger.warning("Token rejected with 401, fetching a new one")
            try:
                await self._fetch()
            except httpx.HTTPError as e:
                self.logger.warning("Token fetch failed: %s", e)
                return False
        return True

    async def _fetch(self) -> None:
        self._last_fetch = time.monotonic()
        self._token = await self._fetch_token()
