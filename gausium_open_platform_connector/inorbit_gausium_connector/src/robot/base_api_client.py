# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""
Base API client for REST API interactions.

This module provides the BaseAPIClient abstract class that handles common HTTP operations,
authentication, error handling, and retry logic for API clients.
"""

import logging
import time
from abc import ABC
from typing import Any

import httpx
from pydantic import BaseModel
from pydantic import HttpUrl
from tenacity import retry
from tenacity import retry_if_exception_type
from tenacity import stop_after_attempt
from tenacity import wait_fixed


# OAuth2 token request URL for Gausium API
REQUEST_TOKEN_URL = "https://openapi.gs-robot.com/gas/api/v1alpha1/oauth/token"


# JWT token dataclass for authenticating against the API
class JWT(BaseModel):
    access_token: str
    refresh_token: str
    expires_at_ms: int


class BaseAPIClient(ABC):
    """Base class for REST API clients with built-in retry logic and error handling."""

    def __init__(
        self,
        base_url: HttpUrl,
        api_req_timeout: int = 10,
        client_id: str | None = None,
        client_secret: str | None = None,
        access_key_secret: str | None = None,
    ):
        """Initializes the connection with the API

        Args:
            base_url (HttpUrl): Base URL of the API. e.g. "http://192.168.0.256:80/"
            api_req_timeout (int, optional): Default timeout for API requests. Defaults to 10.
            client_id (str, optional): Client ID for OAuth authentication. Defaults to None.
            client_secret (str, optional): Client secret for OAuth authentication. Defaults to None.
            access_key_secret (str, optional): Access key secret for OAuth authentication.
                Defaults to None.
        """
        self.logger = logging.getLogger(name=self.__class__.__name__)
        # Use str(base_url) because httpx requires string URLs
        self.base_url = str(base_url)
        self.api_req_timeout = api_req_timeout
        # Indicates whether the last call to the API was successful
        # Useful for estimating the state of the Connector <> APIs link
        # Should only be set to False if the call failed due to an exception
        self._last_call_successful: bool | None = None

        # Store OAuth credentials
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_key_secret = access_key_secret
        self.token: JWT | None = None

        # Initialize httpx.AsyncClient without auth initially (will be set after token fetch)
        self.api_client = httpx.AsyncClient(base_url=self.base_url, timeout=self.api_req_timeout)

        # If the log level is INFO, reduce the verbosity of httpx
        if self.logger.getEffectiveLevel() == logging.INFO:
            logging.getLogger("httpx").setLevel(logging.WARNING)

    async def init_session(self) -> None:
        """Initialize the API session by fetching OAuth token."""
        if not all([self.client_id, self.client_secret, self.access_key_secret]):
            raise ValueError("OAuth credentials are required for API authentication")

        self.logger.info("Fetching API credentials")

        # Use a separate client for token requests
        async with httpx.AsyncClient() as token_client:
            response = await token_client.post(
                REQUEST_TOKEN_URL,
                headers={"Content-Type": "application/json"},
                json={
                    "grant_type": "urn:gaussian:params:oauth:grant-type:open-access-token",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "open_access_key": self.access_key_secret,
                },
            )
            response.raise_for_status()

        token_data = response.json()
        self.token = JWT(
            access_token=token_data["access_token"],
            refresh_token=token_data["refresh_token"],
            expires_at_ms=token_data["expires_in"],
        )

        # Update the API client with the authorization header
        self.api_client.headers.update(
            {
                "Authorization": f"Bearer {self.token.access_token}",
                "Content-Type": "application/json",
            }
        )
        self.logger.info("API session initialized")

    async def _refresh_token(self) -> None:
        """Refresh the OAuth token."""
        if not self.token:
            raise ValueError("No token available to refresh")

        async with httpx.AsyncClient() as token_client:
            response = await token_client.post(
                REQUEST_TOKEN_URL,
                headers={"Content-Type": "application/json"},
                json={
                    "grant_type": "refresh_token",
                    "refresh_token": self.token.refresh_token,
                },
            )
            response.raise_for_status()

        token_data = response.json()
        self.token = JWT(
            access_token=token_data["access_token"],
            refresh_token=token_data["refresh_token"],
            expires_at_ms=token_data["expires_in"],
        )

        # Update the API client with the new authorization header
        self.api_client.headers.update(
            {
                "Authorization": f"Bearer {self.token.access_token}",
            }
        )

    def _check_token_or_refresh(self) -> None:
        """Check if the token is still valid, if not, schedule a refresh."""
        if self.token and self.token.expires_at_ms < time.time() * 1000:
            # Note: In async context, we should handle this properly
            # For now, we'll let the caller handle the refresh
            pass

    async def close(self) -> None:
        """Closes the httpx client session."""
        await self.api_client.aclose()
        self.logger.info("HTTPX client closed.")

    @staticmethod
    def retry(func):
        """Utility decorator to retry the function upon API failure. It retries if the call fails
        due to a RequestError, but does not retry if the call is successful, regardless of the
        status code or other response characteristics.

        Args:
            func (function): The function to retry.
        """
        return retry(
            reraise=True,
            retry=retry_if_exception_type(httpx.RequestError),
            before_sleep=lambda retry_state: logging.getLogger(func.__name__).warning(
                f"Retrying {func.__name__} in {retry_state.next_action.sleep} seconds"
            ),
            after=lambda retry_state: logging.getLogger(func.__name__).warning(
                f"Retried {func.__name__} {retry_state.attempt_number} times"
            ),
            stop=stop_after_attempt(3),
            wait=wait_fixed(0.5),
        )(func)

    @property
    def last_call_successful(self) -> bool:
        """Get the last call successful status.
        This is defined by whether the last API call succeeded, regardless of its status code"""
        return self._last_call_successful

    def _handle_status(self, res: httpx.Response, request_args: dict[str, Any]) -> None:
        """Log and raise an exception if the request failed. Update the status of the last call if
        required"""
        # Set the last call successful status to False.
        # It is set to true if the call successds regardless of the status code
        self._last_call_successful = False

        try:
            res.raise_for_status()
            self._last_call_successful = True
        except httpx.HTTPStatusError as e:
            self.logger.error(f"Error making request: {e.request.method} {e.request.url}")
            self.logger.error(f"Arguments: {request_args}")
            self.logger.error(f"Response Status: {e.response.status_code}")
            self.logger.error(f"Response Body: {e.response.text[:500]}...")

            # On status errors, set the last call successful status to True
            self._last_call_successful = True

            # Handle token refresh for 401 errors
            if e.response.status_code == 401:
                self.logger.info("Attempting to refresh token")
                # Note: In a real implementation, you might want to schedule a token refresh
                # and retry the request. For now, we'll just log and re-raise.

            raise e

    async def _get(self, endpoint: str, timeout: int | None = None, **kwargs) -> httpx.Response:
        """Perform a GET request."""
        # Check token expiry before making request
        if self.token and self.token.expires_at_ms < time.time() * 1000:
            await self._refresh_token()

        url_for_logging = self.base_url + endpoint.lstrip("/")
        self.logger.debug(f"GETting {url_for_logging}: {kwargs}")
        try:
            res = await self.api_client.get(
                endpoint, timeout=timeout or self.api_req_timeout, **kwargs
            )
            self._handle_status(res, kwargs)
            return res
        except httpx.RequestError as e:
            self._last_call_successful = False
            self.logger.error(f"HTTPX GET Error for {endpoint}: {str(e) or e.__class__.__name__}")
            raise e

    async def _post(self, endpoint: str, timeout: int | None = None, **kwargs) -> httpx.Response:
        """Perform a POST request."""
        # Check token expiry before making request
        if self.token and self.token.expires_at_ms < time.time() * 1000:
            await self._refresh_token()

        url_for_logging = self.base_url + endpoint.lstrip("/")
        self.logger.debug(f"POSTing {url_for_logging}: {kwargs}")
        try:
            res = await self.api_client.post(
                endpoint, timeout=timeout or self.api_req_timeout, **kwargs
            )
            log_body = res.text[:200] + "..." if len(res.text) > 200 else res.text
            self.logger.debug(f"Response status: {res.status_code}, Response body: {log_body}")
            self._handle_status(res, kwargs)
            return res
        except httpx.RequestError as e:
            self._last_call_successful = False
            self.logger.error(f"HTTPX POST Error for {endpoint}: {str(e) or e.__class__.__name__}")
            raise e

    async def _delete(self, endpoint: str, timeout: int | None = None, **kwargs) -> httpx.Response:
        """Perform a DELETE request."""
        # Check token expiry before making request
        if self.token and self.token.expires_at_ms < time.time() * 1000:
            await self._refresh_token()

        url_for_logging = self.base_url + endpoint.lstrip("/")
        self.logger.debug(f"DELETEing {url_for_logging}: {kwargs}")
        try:
            res = await self.api_client.delete(
                endpoint, timeout=timeout or self.api_req_timeout, **kwargs
            )
            log_body = res.text[:200] + "..." if len(res.text) > 200 else res.text
            self.logger.debug(f"Response status: {res.status_code}, Response body: {log_body}")
            self._handle_status(res, kwargs)
            return res
        except httpx.RequestError as e:
            self._last_call_successful = False
            self.logger.error(
                f"HTTPX DELETE Error for {endpoint}: {str(e) or e.__class__.__name__}"
            )
            raise e

    async def _put(self, endpoint: str, timeout: int | None = None, **kwargs) -> httpx.Response:
        """Perform a PUT request."""
        # Check token expiry before making request
        if self.token and self.token.expires_at_ms < time.time() * 1000:
            await self._refresh_token()

        url_for_logging = self.base_url + endpoint.lstrip("/")
        self.logger.debug(f"PUTing {url_for_logging}: {kwargs}")
        try:
            res = await self.api_client.put(
                endpoint, timeout=timeout or self.api_req_timeout, **kwargs
            )
            self.logger.debug(
                f"Response status: {res.status_code}, Response body: {res.text[:200]}..."
            )
            self._handle_status(res, kwargs)
            return res
        except httpx.RequestError as e:
            self._last_call_successful = False
            self.logger.error(f"HTTPX PUT Error for {endpoint}: {str(e) or e.__class__.__name__}")
            raise e
