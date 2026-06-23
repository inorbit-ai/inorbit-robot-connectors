# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Tests for the MiR metrics helpers.

The endpoint normalizer feeds the canonical upstream-HTTP metrics — every
raw MiR API path must collapse into the bounded label set; a regression
here silently pollutes the metric descriptor.
"""

import httpx
import pytest

from inorbit_mir_connector.src.metrics import api_endpoint, error_kind


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/api/v2.0.0/status", "status"),
        ("/api/v2.0.0/metrics", "metrics"),
        ("/api/v2.0.0/experimental/diagnostics", "diagnostics"),
        ("/api/v2.0.0/mission_queue/14026", "mission_queue"),
        ("/api/v2.0.0/mission_groups/abc-123/missions", "mission_groups"),
        ("/api/v2.0.0/missions/71e63050-7b7a-11ed", "missions"),
        ("/api/v2.0.0/maps/20f762ff-5e0a-11ee", "maps"),
        # Callers may pass relative paths (httpx base_url joins them).
        ("status", "status"),
        ("mission_queue/14026", "mission_queue"),
        # Leading-slash relative paths — the shape mir_api_v2.py actually
        # passes to the shared httpx client (base_url joins them).
        ("/status", "status"),
        ("/metrics", "metrics"),
        ("/missions", "missions"),
        ("/mission_queue/14026", "mission_queue"),
        ("/mission_groups", "mission_groups"),
        # Unknown paths collapse instead of leaking raw values.
        ("/api/v2.0.0/registers/42", "other"),
        ("", "other"),
    ],
)
def test_api_endpoint_normalization(path, expected):
    assert api_endpoint(path) == expected


def test_label_set_is_bounded_across_ids():
    """Different mission/queue ids must not fan out into new labels."""
    labels = {api_endpoint(f"/api/v2.0.0/mission_queue/{i}") for i in range(100)}
    labels |= {api_endpoint(f"/api/v2.0.0/missions/m-{i}") for i in range(100)}
    assert labels == {"mission_queue", "missions"}


def test_error_kind_is_bounded():
    """error_kind must only emit values from the framework's bounded enum."""
    request = httpx.Request("GET", "http://example.com")

    def http_error(status):
        response = httpx.Response(status, request=request)
        return httpx.HTTPStatusError("err", request=request, response=response)

    cases = [
        (httpx.ConnectTimeout("t"), "timeout"),
        (httpx.ConnectError("c"), "connect_error"),
        (http_error(404), "http_4xx"),
        (http_error(503), "http_5xx"),
        # Non-error HTTP statuses and unknown exceptions collapse to "other"
        # so the descriptor's label space stays bounded.
        (http_error(302), "other"),
        (ValueError("v"), "other"),
    ]
    for exc, expected in cases:
        assert error_kind(exc) == expected
