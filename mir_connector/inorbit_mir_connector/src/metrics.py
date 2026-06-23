# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Metrics helpers for the MiR connector.

This connector does not declare domain instruments of its own: all metrics
are recorded on the ``inorbit_connector`` framework's canonical families.
HTTP request/error/duration signals go through
``record_upstream_http_request`` / ``record_upstream_http_error`` from the
call sites in ``mir_api_base.py`` / ``mir_api_v2.py``; this module only
provides the endpoint normalizer (:func:`api_endpoint`) and the
:func:`error_kind` mapper feeding those calls.

NOTE: tenacity retry attempts against the MiR API (previously a
connector-local counter) are intentionally NOT recorded for now — they
should land as a canonical upstream-HTTP family (e.g.
``upstream.http.retries`` with vendor/method/endpoint labels) in the
inorbit-connector framework rather than as a per-connector instrument. See
``_record_retry`` in ``mir_api_base.py``.
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


# Endpoint normalizer for the canonical upstream-HTTP metrics. MiR API
# routes are static (``/api/v2.0.0/<family>/...``), so an explicit prefix
# table is preferred over PathTemplater. Longest prefix wins; unknown paths
# collapse to "other" so dynamic IDs never blow up Prometheus cardinality.
#
# Table entries carry NO leading slash: api_endpoint() strips the slash off
# the incoming path so one table covers every shape callers pass (absolute
# ``/api/v2.0.0/status``, relative ``/status`` or ``status``).
#
# Trade-off: EndpointMapper matches plain prefixes with no segment-boundary
# guard. That is fine for the frozen v2.0.0 route families (none is a prefix
# of another), but revisit if new routes share a leading prefix.
_api_endpoint_mapper = EndpointMapper(
    [
        ("api/v2.0.0/status", "status"),
        ("api/v2.0.0/metrics", "metrics"),
        ("api/v2.0.0/experimental/diagnostics", "diagnostics"),
        ("api/v2.0.0/mission_queue", "mission_queue"),
        ("api/v2.0.0/mission_groups", "mission_groups"),
        ("api/v2.0.0/missions", "missions"),
        ("api/v2.0.0/maps", "maps"),
        # Bare-prefix variants (callers may pass relative paths)
        ("status", "status"),
        ("metrics", "metrics"),
        ("experimental/diagnostics", "diagnostics"),
        ("mission_queue", "mission_queue"),
        ("mission_groups", "mission_groups"),
        ("missions", "missions"),
        ("maps", "maps"),
    ]
)


def api_endpoint(path: str) -> str:
    """Collapse a raw MiR API path into a bounded endpoint label.

    Paths arrive in several shapes (absolute ``/api/v2.0.0/status``,
    relative ``/status`` or ``status``); the leading slash is stripped so
    one prefix table covers all of them.
    """
    return _api_endpoint_mapper(path.lstrip("/"))
