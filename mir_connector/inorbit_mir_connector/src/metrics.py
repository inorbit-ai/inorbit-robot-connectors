# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""OpenTelemetry instruments for the MiR connector domain.

Instruments declared here flow through the global MeterProvider that the
``inorbit_connector.connector.Connector`` base class installs when
``config.metrics.enabled`` is True. When metrics are disabled (the default),
``inorbit_edge.metrics.get_meter`` returns a no-op meter and every call below
becomes a cheap no-op — call sites can use the instruments unconditionally
without guarding on configuration.

Domain instrument groups:

* HTTP layer (``mir_api_*``) — request count, retry count, and duration
  histogram for every call against the MiR robot API. Outcomes are bucketed
  via :func:`classify_outcome`; endpoint paths are reduced to a bounded set
  via :func:`endpoint_label` to keep Prometheus cardinality finite.
* Polling layer (``mir_polling_*``) — per-loop tick counter plus an
  ObservableGauge reporting seconds elapsed since the last successful poll.
  A growing ``last_success_age`` is the deadlock signal called out in
  PLATFORM-3056.
* Circuit breaker (``mir_circuit_breaker_opens``) — counts trips of the
  circuit breaker pattern in :class:`Robot` (>= max_consecutive_errors).
"""

import time
from typing import Optional

import httpx
from inorbit_edge.metrics import Observation, get_meter

METER_NAME = "inorbit_mir_connector"
_meter = get_meter(METER_NAME)


# --- HTTP layer (deadlock-detection signal #1) ----------------------------

mir_api_requests_total = _meter.create_counter(
    "mir_api_requests",
    unit="1",
    description="Total HTTP requests to the MiR robot API, labeled by method, "
    "endpoint, and outcome",
)

mir_api_request_duration_seconds = _meter.create_histogram(
    "mir_api_request_duration_seconds",
    unit="s",
    description="Wall-clock duration of HTTP requests to the MiR robot API. "
    "Rising p99 is an early deadlock signal.",
)

mir_api_retries_total = _meter.create_counter(
    "mir_api_retries",
    unit="1",
    description="Number of tenacity retry attempts against the MiR robot API",
)


# --- Polling layer (deadlock-detection signal #2) -------------------------

mir_polling_ticks_total = _meter.create_counter(
    "mir_polling_ticks",
    unit="1",
    description="Robot data polling iterations, labeled by loop and outcome",
)


# --- Circuit breaker ------------------------------------------------------

mir_circuit_breaker_opens_total = _meter.create_counter(
    "mir_circuit_breaker_opens",
    unit="1",
    description="Number of times the polling circuit breaker tripped "
    "(consecutive errors >= threshold)",
)


# --- Helpers --------------------------------------------------------------


def classify_outcome(exc: Optional[BaseException]) -> str:
    """Map an exception (or None for success) to a bounded label value.

    Used as the ``outcome`` attribute on HTTP and polling metrics.
    """
    if exc is None:
        return "success"
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
        return "http_other"
    return "error"


# Mapping table for endpoint label reduction. Order matters: more specific
# prefixes must come before less specific ones. Each entry is
# ``(prefix, label)``; the first prefix that matches wins.
_ENDPOINT_PREFIXES: list[tuple[str, str]] = [
    ("/api/v2.0.0/status", "status"),
    ("/api/v2.0.0/metrics", "metrics"),
    ("/api/v2.0.0/experimental/diagnostics", "diagnostics"),
    ("/api/v2.0.0/mission_queue", "mission_queue"),
    ("/api/v2.0.0/mission_groups", "mission_groups"),
    ("/api/v2.0.0/missions", "missions"),
    ("/api/v2.0.0/maps", "maps"),
    # Bare-prefix variants (callers may pass relative paths)
    ("status", "status"),
    ("metrics", "metrics"),
    ("experimental/diagnostics", "diagnostics"),
    ("mission_queue", "mission_queue"),
    ("mission_groups", "mission_groups"),
    ("missions", "missions"),
    ("maps", "maps"),
]


def endpoint_label(path: str) -> str:
    """Reduce a MiR API path to a bounded label value.

    Any unknown path collapses to ``"other"`` so we never let dynamic IDs
    blow up Prometheus cardinality.
    """
    if not path:
        return "other"
    normalized = path.lstrip("/")
    for prefix, label in _ENDPOINT_PREFIXES:
        prefix_normalized = prefix.lstrip("/")
        if normalized == prefix_normalized or normalized.startswith(
            prefix_normalized + "/"
        ):
            return label
    return "other"


# --- ObservableGauge registration ----------------------------------------


def register_polling_liveness_gauge(robot) -> None:
    """Register the ``mir_polling_last_success_age_seconds`` ObservableGauge.

    Reads ``robot._last_success_ts`` (a ``dict[str, float]`` of monotonic
    timestamps keyed by loop name) on every Prometheus scrape and reports
    ``time.monotonic() - ts`` per loop. Loops that have never succeeded
    report 0.0.

    Should be called once from :meth:`Robot.start` after the polling tasks
    are launched. Safe to call when the global MeterProvider is the OTEL
    no-op provider (``create_observable_gauge`` becomes a no-op).
    """

    def _callback(_options):
        now = time.monotonic()
        observations = []
        for loop_name, ts in robot._last_success_ts.items():
            age = now - ts if ts else 0.0
            observations.append(Observation(age, {"loop": loop_name}))
        return observations

    _meter.create_observable_gauge(
        "mir_polling_last_success_age_seconds",
        callbacks=[_callback],
        unit="s",
        description="Seconds elapsed since the last successful poll, by loop. "
        "Rising values indicate a stalled polling loop / potential deadlock.",
    )
