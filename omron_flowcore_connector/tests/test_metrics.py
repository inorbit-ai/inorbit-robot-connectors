# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Tests for the upstream-HTTP metrics helpers."""

import httpx
import pytest

from inorbit_omron_connector.src.metrics import api_endpoint, error_kind


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/Robot/UpdatedSince?sinceTime=0", "robot_updated_since"),
        ("/DataStoreValueLatest/BatteryStateOfCharge:Robot1", "data_store_value_latest"),
        ("/JobRequest", "job_request"),
        ("/JobCancel", "job_cancel"),
        ("/Job/Stream", "job_stream"),
        ("/JobSegment/Stream", "job_segment_stream"),
        ("/JobSegment/ByJob/JOB123", "job_segment_by_job"),
        ("/Job/ByJobId/abc-123", "job_by_job_id"),
        ("/Job/ByKey/JOB123", "job_by_key"),
        ("/Dropoff", "dropoff"),
        ("/SomethingNew/42", "other"),
    ],
)
def test_api_endpoint_normalizes_paths(path, expected):
    assert api_endpoint(path) == expected


def _status_error(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://x.example/JobRequest")
    response = httpx.Response(code, request=request)
    return httpx.HTTPStatusError("err", request=request, response=response)


@pytest.mark.parametrize(
    "exc,expected",
    [
        (httpx.ConnectTimeout("t"), "timeout"),
        (httpx.ReadTimeout("t"), "timeout"),
        (httpx.ConnectError("c"), "connect_error"),
        (_status_error(404), "http_4xx"),
        (_status_error(503), "http_5xx"),
        (ValueError("x"), "other"),
    ],
)
def test_error_kind_maps_exceptions(exc, expected):
    assert error_kind(exc) == expected
