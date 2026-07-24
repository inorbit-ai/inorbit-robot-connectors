# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Metrics helpers for the FlowCore connector.

This connector does not declare domain instruments of its own: all metrics
are recorded on the ``inorbit_connector`` framework's canonical
upstream-HTTP families from the call sites in ``omron/api_client.py``. This
module only provides the endpoint normalizer (:func:`api_endpoint`) and the
:func:`error_kind` mapper feeding those calls. The ARCL TCP client is not
instrumented (the upstream.http family does not fit raw TCP).
"""

import httpx
from inorbit_connector.metrics.http import EndpointMapper


def error_kind(exc: BaseException) -> str:
    """Map an exception to the canonical ``upstream.http`` error_kind enum.

    Bounded set: ``timeout``, ``connect_error``, ``http_4xx``, ``http_5xx``,
    ``other``. The framework coerces unknown kinds to "other" with a
    WARNING; mapping here keeps the logs clean.
    """
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.ConnectError):
        return "connect_error"
    if isinstance(exc, httpx.HTTPStatusError):
        sc = exc.response.status_code
        if 400 <= sc < 500:
            return "http_4xx"
        if 500 <= sc < 600:
            return "http_5xx"
    return "other"


# Endpoint normalizer for the canonical upstream-HTTP metrics. FlowCore API
# routes are static, so an explicit prefix table is preferred over
# PathTemplater. Longest prefix wins; unknown paths collapse to "other" so
# dynamic IDs never blow up Prometheus cardinality.
api_endpoint = EndpointMapper(
    [
        ("/Robot/UpdatedSince", "robot_updated_since"),
        ("/DataStoreValueLatest", "data_store_value_latest"),
        ("/JobRequest", "job_request"),
        ("/JobCancel", "job_cancel"),
        ("/Job/Stream", "job_stream"),
        ("/JobSegment/Stream", "job_segment_stream"),
        ("/JobSegment/ByJob", "job_segment_by_job"),
        ("/Job/ByJobId", "job_by_job_id"),
        ("/Job/ByKey", "job_by_key"),
        ("/Dropoff", "dropoff"),
    ]
)
