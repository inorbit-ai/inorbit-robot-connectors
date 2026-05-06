# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Integration test for the OTEL Prometheus exporter wiring.

Builds a real :class:`MirConnector` with ``metrics.enabled=True``, starts the
metrics HTTP server, exercises both a framework counter and a domain counter,
then scrapes ``/metrics`` and asserts both metric families appear. This
validates that the inorbit-connector 2.3 upgrade correctly hooks into our
domain instruments (declared in ``inorbit_mir_connector.src.metrics``) via
the shared global MeterProvider.

OTEL's MeterProvider is a process-global singleton, so this test deliberately
runs as a single non-parametrized case.
"""

import socket
import urllib.request
from unittest.mock import MagicMock

import pytest
from inorbit_edge.robot import RobotSession

from inorbit_mir_connector.config.connector_model import ConnectorConfig
from inorbit_mir_connector.src.connector import MirConnector
from inorbit_mir_connector.src.metrics import (
    mir_api_request_duration_seconds,
    mir_api_requests_total,
)


def _free_port() -> int:
    """Return a free TCP port on localhost.

    Binds and immediately closes; brief race window is acceptable for tests.
    """
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


@pytest.fixture
def metrics_connector(monkeypatch, tmp_path):
    """Build a MirConnector with metrics enabled on an ephemeral port."""
    monkeypatch.setenv("INORBIT_KEY", "abc123")
    monkeypatch.setattr(RobotSession, "connect", MagicMock())
    port = _free_port()

    connector = MirConnector(
        "mir100-1",
        ConnectorConfig(
            inorbit_robot_key="robot_key",
            location_tz="UTC",
            logging={"log_level": "INFO"},
            connector_type="MiR100",
            connector_version="0.1.0",
            connector_config={
                "mir_host_address": "example.com",
                "mir_host_port": 80,
                "mir_use_ssl": False,
                "mir_username": "user",
                "mir_password": "pass",
                "mir_api_version": "v2.0",
                "mir_firmware_version": "v2",
                "enable_temporary_mission_group": True,
            },
            user_scripts_dir=tmp_path,
            metrics={
                "enabled": True,
                "bind_host": "127.0.0.1",
                "bind_port": port,
                "discovery_dir": None,
            },
        ),
    )
    connector._port = port  # stash for the test to scrape

    # Start only the metrics HTTP server — we don't want to spin up the
    # full connector thread (no real MQTT broker, no real MiR robot) just
    # to verify the exporter wiring.
    assert (
        connector._metrics_server is not None
    ), "metrics_server should be installed when metrics.enabled=True"
    connector._metrics_server.start()
    try:
        yield connector
    finally:
        connector._metrics_server.stop()


def test_metrics_endpoint_serves_framework_and_domain_metrics(metrics_connector):
    # Emit a domain counter and histogram sample. OpenTelemetry's Prometheus
    # exporter only writes families that have at least one observation, so
    # we need to actually call the instruments to verify the wiring.
    attrs = {"method": "GET", "endpoint": "status", "outcome": "success"}
    mir_api_requests_total.add(1, attrs)
    mir_api_request_duration_seconds.record(0.123, attrs)

    url = f"http://127.0.0.1:{metrics_connector._port}/metrics"
    with urllib.request.urlopen(url, timeout=5) as resp:
        assert resp.status == 200
        body = resp.read().decode("utf-8")

    # Framework gauges are registered eagerly in Connector.__init__ via
    # register_framework_gauges, so they appear on every scrape regardless
    # of whether the run loop has started. Note: the Prometheus exporter
    # prefixes every metric with the exporter namespace ("inorbit_connector"),
    # which means the framework instrument "inorbit.connector.up" becomes
    # "inorbit_connector_inorbit_connector_up" in the output.
    assert "inorbit_connector_up" in body
    assert "inorbit_connector_session_connected" in body

    # Domain instruments are exported via the same global MeterProvider, so
    # they pick up the same namespace prefix.
    assert "mir_api_requests_total" in body
    assert "mir_api_request_duration_seconds" in body
