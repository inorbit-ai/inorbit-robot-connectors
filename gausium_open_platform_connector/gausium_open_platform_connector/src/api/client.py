# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Async HTTP client for the Gausium Open Platform API."""

# Standard
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import timedelta
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
from gausium_open_platform_connector.src.api.auth import TokenAuth
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
        ("openapi-server/v1/api/task/report/map-images/query", "report_map_images"),
    ]
)


def _endpoint_label(path: str) -> str:
    """Map a request path to its stable metrics and log label."""
    return _ENDPOINT(_SERIAL_RE.sub("robots/-/", path))


def _error_kind(error: httpx.HTTPError) -> str:
    """Log label for a failure: the status code, or the exception type."""
    if isinstance(error, httpx.HTTPStatusError):
        return str(error.response.status_code)
    return type(error).__name__


@dataclass
class _Failure:
    """An endpoint's ongoing failure streak, from the first failure to the recovery."""

    kind: str
    count: int = 1
    since: float = field(default_factory=time.monotonic)


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
        self._auth = TokenAuth(self._fetch_token)
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout, auth=self._auth)
        # Ongoing failure streak per endpoint, cleared on recovery
        self._failures: dict[str, _Failure] = {}

    async def connect(self) -> None:
        """Fetch the initial OAuth token."""
        await self._auth.token()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def _fetch_token(self) -> str:
        """Fetch an access token; ``auth=None`` keeps this call out of the auth flow."""
        # Always the open-access grant: it is non-interactive, so a refresh-token flow
        # only adds a way to get permanently stuck when the stored token goes stale
        response = await self._request(
            "POST",
            OAUTH_PATH,
            auth=None,
            json={
                "grant_type": "urn:gaussian:params:oauth:grant-type:open-access-token",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "open_access_key": self._access_key_secret,
            },
        )
        # `expires_in` is ignored: the vendor returns an absolute epoch-millisecond deadline
        # rather than the OAuth2 duration its name promises (measured 1787665295159, 23.9 h
        # out), and TokenAuth replaces the token when the server rejects it anyway
        return response.json()["access_token"]

    @retry(
        # Connect-phase failures only: a ReadTimeout may mean the request was delivered,
        # and retrying it would re-send non-idempotent command POSTs
        retry=retry_if_exception_type((httpx.ConnectError, httpx.ConnectTimeout)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Send one request and record its metrics; TokenAuth adds the Bearer header."""
        endpoint = _endpoint_label(path)
        start = time.monotonic()
        try:
            response = await self._client.request(method, path, **kwargs)
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
        """Like ``_request`` but returns ``None`` on failure instead of raising.

        Logs a state change, not a request: the first failure, a change of failure kind, and
        the recovery with the streak it closes. An endpoint failing at the poll rate would
        otherwise flood the log and evict its own history; per-request volume belongs in
        ``upstream.http.errors``.
        """
        endpoint = _endpoint_label(path)
        try:
            response = await self._request(method, path, **kwargs)
        except httpx.HTTPError as e:
            kind = _error_kind(e)
            failure = self._failures.get(endpoint)
            if failure is None:
                self._failures[endpoint] = _Failure(kind)
            else:
                failure.count += 1
                if failure.kind == kind:
                    return None
                failure.kind = kind
            self.logger.warning("%s failed: %s", endpoint, kind)
            return None
        if failure := self._failures.pop(endpoint, None):
            self.logger.warning(
                "%s recovered after %d failures over %s",
                endpoint,
                failure.count,
                timedelta(seconds=round(time.monotonic() - failure.since)),
            )
        return response

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

    async def get_report_map_images(
        self, serial_number: str, task_report_id: str
    ) -> list[dict] | None:
        """Fetch the coverage map image entries of one task report (RPC-style POST read)."""
        response = await self._fetch(
            "POST",
            "openapi-server/v1/api/task/report/map-images/query",
            json={"robotSn": serial_number, "taskReportId": task_report_id},
        )
        if response is None:
            return None
        return response.json().get("data", [])

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
