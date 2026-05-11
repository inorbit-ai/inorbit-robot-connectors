# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Unit tests for the connector's domain metrics module."""

import httpx
import pytest

from inorbit_mir_connector.src.metrics import (
    classify_outcome,
    endpoint_label,
    mir_api_request_duration_seconds,
    mir_api_requests_total,
    mir_api_retries_total,
    mir_circuit_breaker_opens_total,
    mir_polling_ticks_total,
)


class TestInstrumentsHaveCallableApi:
    """Importing the metrics module yields instruments with the OTEL public API.

    These call sites are exercised throughout the codebase regardless of
    whether metrics are enabled — when disabled they're OTEL no-ops, but they
    must still expose ``add`` / ``record`` so callers don't need to guard.
    """

    def test_counters_have_add(self):
        for counter in (
            mir_api_requests_total,
            mir_api_retries_total,
            mir_polling_ticks_total,
            mir_circuit_breaker_opens_total,
        ):
            assert callable(getattr(counter, "add", None))

    def test_histogram_has_record(self):
        assert callable(getattr(mir_api_request_duration_seconds, "record", None))

    def test_calling_instruments_does_not_raise(self):
        # All instruments should accept calls cleanly even with no provider.
        mir_api_requests_total.add(1, {"method": "GET", "endpoint": "status"})
        mir_api_retries_total.add(1, {"method": "GET", "endpoint": "status"})
        mir_polling_ticks_total.add(1, {"loop": "status", "outcome": "success"})
        mir_circuit_breaker_opens_total.add(1)
        mir_api_request_duration_seconds.record(
            0.123, {"method": "GET", "endpoint": "status", "outcome": "success"}
        )


class TestClassifyOutcome:
    """``classify_outcome`` maps exceptions into a bounded label set."""

    def test_success_when_none(self):
        assert classify_outcome(None) == "success"

    def test_timeout(self):
        assert classify_outcome(httpx.ConnectTimeout("boom")) == "timeout"
        assert classify_outcome(httpx.ReadTimeout("boom")) == "timeout"

    def test_connect_error(self):
        assert classify_outcome(httpx.ConnectError("boom")) == "connect_error"

    @pytest.mark.parametrize("status_code", [400, 404, 422, 499])
    def test_http_4xx(self, status_code):
        request = httpx.Request("GET", "http://example/x")
        response = httpx.Response(status_code, request=request)
        exc = httpx.HTTPStatusError("boom", request=request, response=response)
        assert classify_outcome(exc) == "http_4xx"

    @pytest.mark.parametrize("status_code", [500, 502, 503, 504, 599])
    def test_http_5xx(self, status_code):
        request = httpx.Request("GET", "http://example/x")
        response = httpx.Response(status_code, request=request)
        exc = httpx.HTTPStatusError("boom", request=request, response=response)
        assert classify_outcome(exc) == "http_5xx"

    def test_http_other_code(self):
        # Codes outside 4xx/5xx are bucketed separately
        request = httpx.Request("GET", "http://example/x")
        response = httpx.Response(302, request=request)
        exc = httpx.HTTPStatusError("boom", request=request, response=response)
        assert classify_outcome(exc) == "http_other"

    def test_generic_exception(self):
        assert classify_outcome(RuntimeError("boom")) == "error"
        assert classify_outcome(ValueError("boom")) == "error"


class TestEndpointLabel:
    """``endpoint_label`` reduces paths to a bounded label set."""

    @pytest.mark.parametrize(
        "path,expected",
        [
            # Absolute paths as MirApiBase uses them
            ("/api/v2.0.0/status", "status"),
            ("/api/v2.0.0/metrics", "metrics"),
            ("/api/v2.0.0/experimental/diagnostics", "diagnostics"),
            ("/api/v2.0.0/mission_queue", "mission_queue"),
            ("/api/v2.0.0/mission_queue/14026", "mission_queue"),
            ("/api/v2.0.0/mission_queue/14026/actions", "mission_queue"),
            ("/api/v2.0.0/missions", "missions"),
            ("/api/v2.0.0/missions/abc-123", "missions"),
            ("/api/v2.0.0/missions/abc-123/actions", "missions"),
            ("/api/v2.0.0/mission_groups", "mission_groups"),
            ("/api/v2.0.0/mission_groups/X/missions", "mission_groups"),
            ("/api/v2.0.0/maps", "maps"),
            ("/api/v2.0.0/maps/20f762ff-5e0a-11ee-abc8-0001299981c4", "maps"),
            # Bare-prefix variants
            ("status", "status"),
            ("metrics", "metrics"),
            ("mission_queue/123", "mission_queue"),
            # Unknown
            ("/some/random/path", "other"),
            ("/api/v2.0.0/users", "other"),
            ("", "other"),
        ],
    )
    def test_path_mapping(self, path, expected):
        assert endpoint_label(path) == expected
