# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Async HTTP client for the Gausium Open Platform API."""

# Standard
import asyncio
import logging
import re
import time
from typing import Any

# Third-party
import httpx

# InOrbit
from inorbit_connector.metrics.http import (
    EndpointMapper,
    record_upstream_http_error,
    record_upstream_http_request,
)
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

# Local
from gausium_open_platform_connector.src.commands import (
    RemoteNavigationCommandType,
    RemoteTaskCommandType,
)

logger = logging.getLogger(__name__)

VENDOR = "gausium_open_platform"

OAUTH_PATH = "gas/api/v1alpha1/oauth/token"

# Serial numbers are masked before mapping so per-robot paths collapse into one label each.
_SERIAL_RE = re.compile(r"robots/[^/*-][^/]*/")

_ENDPOINT = EndpointMapper(
    [
        (OAUTH_PATH, "oauth"),
        ("v1alpha1/robots/-/status:batchGet", "status_v1_batch"),
        ("v1alpha1/robots/-/commands", "commands"),
        ("v1alpha1/robots", "robots"),
        ("openapi/v2alpha1/s/robots/*/status:batchGet", "status_v2_batch"),
        ("openapi/v2alpha1/robots/-/taskReports", "task_reports_v2"),
        ("openapi/v2alpha1/robots/-/map", "map"),
        ("openapi/v2alpha1/robotCommand/tempTask:send", "temp_task"),
    ]
)


class GausiumApiClient:
    """Account-scoped Gausium Open Platform API client (one OAuth session, N robots).

    Data methods return ``None`` on any failure so callers keep cached values; command
    methods raise so callers can report a command failure.
    """

    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: str,
        access_key_secret: str,
        timeout: float = 10.0,
    ) -> None:
        """Initialize the client.

        Args:
            base_url: Base URL of the API (e.g. ``https://openapi.gs-robot.com/``).
            client_id: OAuth client ID.
            client_secret: OAuth client secret.
            access_key_secret: OAuth open access key.
            timeout: Request timeout in seconds.
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self._client_id = client_id
        self._client_secret = client_secret
        self._access_key_secret = access_key_secret
        self._timeout = timeout
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)
        self._access_token: str | None = None
        self._token_expiry: float = 0.0
        self._token_lock = asyncio.Lock()

    async def connect(self) -> None:
        """Fetch the initial OAuth token."""
        await self._fetch_token()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def _fetch_token(self) -> None:
        # Always the open-access grant: it is non-interactive, so a refresh-token flow
        # only adds a way to get permanently stuck when the stored token goes stale
        response = await self._request(
            "POST",
            OAUTH_PATH,
            json={
                "grant_type": "urn:gaussian:params:oauth:grant-type:open-access-token",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "open_access_key": self._access_key_secret,
            },
        )
        data = response.json()
        self._access_token = data["access_token"]
        self._token_expiry = time.monotonic() + data["expires_in"] - 60

    async def _ensure_token(self) -> None:
        if time.monotonic() < self._token_expiry:
            return
        # Concurrent callers (the two batch polls run gathered) must not both fetch
        async with self._token_lock:
            if time.monotonic() >= self._token_expiry:
                await self._fetch_token()

    @retry(
        # Connect-phase failures only: a ReadTimeout may mean the request was delivered,
        # and retrying it would re-send non-idempotent command POSTs
        retry=retry_if_exception_type((httpx.ConnectError, httpx.ConnectTimeout)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Send one request with Bearer auth, token refresh and metrics recording."""
        if path != OAUTH_PATH:
            await self._ensure_token()
        headers = kwargs.pop("headers", {})
        if self._access_token and path != OAUTH_PATH:
            headers["Authorization"] = f"Bearer {self._access_token}"
        endpoint = _ENDPOINT(_SERIAL_RE.sub("robots/-/", path))
        start = time.monotonic()
        try:
            response = await self._client.request(method, path, headers=headers, **kwargs)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            kind = "http_5xx" if e.response.status_code >= 500 else "http_4xx"
            self._record_error(method, endpoint, kind, start)
            raise
        except httpx.TimeoutException:
            self._record_error(method, endpoint, "timeout", start)
            raise
        except httpx.ConnectError:
            self._record_error(method, endpoint, "connect_error", start)
            raise
        except httpx.HTTPError:
            self._record_error(method, endpoint, "other", start)
            raise
        record_upstream_http_request(
            vendor=VENDOR,
            method=method,
            endpoint=endpoint,
            duration_seconds=time.monotonic() - start,
        )
        return response

    @staticmethod
    def _record_error(method: str, endpoint: str, kind: str, start: float) -> None:
        record_upstream_http_error(
            vendor=VENDOR,
            method=method,
            endpoint=endpoint,
            error_kind=kind,
            duration_seconds=time.monotonic() - start,
        )

    async def _fetch(self, method: str, path: str, **kwargs: Any) -> httpx.Response | None:
        """Like ``_request`` but returns ``None`` on failure instead of raising."""
        try:
            return await self._request(method, path, **kwargs)
        except httpx.HTTPError as e:
            self.logger.warning("Request %s %s failed: %s", method, path, e)
            return None

    # --- Data methods (None on failure) ------------------------------------

    async def batch_status_v1(self, serial_numbers: list[str]) -> dict[str, dict] | None:
        """Fetch v1 batch status; returns per-serial-number status dicts."""
        # `names` is a repeated query param; a comma-joined list is read as one name and 403s
        response = await self._fetch(
            "GET",
            "v1alpha1/robots/-/status:batchGet",
            params=[("names", serial_number) for serial_number in serial_numbers],
        )
        if response is None:
            return None
        return {s["serialNumber"]: s for s in response.json().get("robotStatuses", [])}

    async def batch_status_v2(self, serial_numbers: list[str]) -> dict[str, dict] | None:
        """Fetch v2 batch status; returns per-serial-number status dicts."""
        # Vendor quirk: GET with a JSON body; `names` must be a list (verified working live)
        response = await self._fetch(
            "GET",
            "openapi/v2alpha1/s/robots/*/status:batchGet",
            json={"names": serial_numbers},
        )
        if response is None:
            return None
        return {s["serialNumber"]: s for s in response.json().get("robotStatus", [])}

    async def get_robots(self, page: int = 1, page_size: int = 100) -> dict | None:
        """Fetch one page of the account robot list (raw ``{"robots": [...]}`` response)."""
        response = await self._fetch(
            "GET",
            "v1alpha1/robots",
            params={"page": page, "pageSize": page_size, "relation": "cugrup"},
        )
        return None if response is None else response.json()

    async def get_task_reports_v2(
        self, serial_number: str, page: int = 1, page_size: int = 10
    ) -> list[dict] | None:
        """Fetch v2 task reports for one robot."""
        response = await self._fetch(
            "GET",
            f"openapi/v2alpha1/robots/{serial_number}/taskReports",
            params={"page": page, "pageSize": page_size},
        )
        if response is None:
            return None
        return response.json().get("robotTaskReports", [])

    async def get_map_image(
        self, serial_number: str, map_id: str, map_name: str, map_version: str
    ) -> bytes | None:
        """Fetch the PNG image of a robot map via its pre-signed download URI."""
        response = await self._fetch(
            "GET",
            f"openapi/v2alpha1/robots/{serial_number}/map",
            params={"mapId": map_id, "mapName": map_name, "mapVersion": map_version},
        )
        if response is None:
            return None
        download_uri = response.json().get("downloadUri")
        if not download_uri:
            self.logger.warning("No downloadUri in map response for %s", serial_number)
            return None
        # The download URI is absolute and pre-signed: fetch it without auth headers.
        # TODO: record this download in the upstream HTTP metrics (label "map_download");
        # it is the only call that bypasses _request
        try:
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=max(self._timeout, 30)
            ) as download_client:
                image = await download_client.get(download_uri)
                image.raise_for_status()
        except httpx.HTTPError as e:
            self.logger.warning("Map image download failed for %s: %s", serial_number, e)
            return None
        return image.content

    # --- Command methods (raise on failure) ---------------------------------

    async def send_remote_task_command(
        self,
        serial_number: str,
        command_type: RemoteTaskCommandType,
        command_parameter: dict | None = None,
    ) -> dict:
        """Send a remote task command (start/pause/resume/stop) to a robot."""
        payload: dict[str, Any] = {
            "serialNumber": serial_number,
            "remoteTaskCommandType": command_type,
        }
        if command_parameter:
            payload["commandParameter"] = command_parameter
        response = await self._request(
            "POST", f"v1alpha1/robots/{serial_number}/commands", json=payload
        )
        return response.json()

    async def send_remote_navigation_command(
        self,
        serial_number: str,
        command_type: RemoteNavigationCommandType,
        command_parameter: dict | None = None,
    ) -> dict:
        """Send a remote navigation command to a robot."""
        payload: dict[str, Any] = {
            "serialNumber": serial_number,
            "remoteNavigationCommandType": command_type,
        }
        if command_parameter:
            payload["commandParameter"] = command_parameter
        response = await self._request(
            "POST", f"v1alpha1/robots/{serial_number}/commands", json=payload
        )
        return response.json()

    async def create_nosite_task(
        self,
        serial_number: str,
        task_name: str,
        map_id: str,
        map_name: str,
        area_id: str,
        cleaning_mode: str,
        loop: bool = False,
        loop_count: int = 1,
    ) -> dict:
        """Submit a temporary no-site cleaning task to a robot."""
        payload = {
            "productId": serial_number,
            "tempTaskCommand": {
                "taskName": task_name,
                "cleaningMode": cleaning_mode,
                "loop": str(loop).lower(),
                "loopCount": str(loop_count),
                "mapName": map_name,
                "startParam": {"mapId": map_id, "areaId": area_id},
            },
        }
        response = await self._request(
            "POST", "openapi/v2alpha1/robotCommand/tempTask:send", json=payload
        )
        return response.json()
