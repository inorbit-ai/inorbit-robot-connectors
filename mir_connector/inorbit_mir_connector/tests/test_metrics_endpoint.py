# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Integration test for the OTel Prometheus exporter wiring.

Builds a real :class:`MirConnector` with ``metrics.enabled=True``, starts the
metrics HTTP server, exercises a framework gauge and the canonical
upstream-HTTP family, then scrapes ``/metrics`` and asserts the metric
families appear under the single ``inorbit_connector`` wire namespace.

OTel's MeterProvider is a process-global singleton, so this test deliberately
runs as a single non-parametrized case.
"""

import socket
import urllib.request
from unittest.mock import MagicMock

import pytest
from inorbit_connector.metrics.http import record_upstream_http_request
from inorbit_edge.robot import RobotSession

from inorbit_mir_connector.config.connector_model import ConnectorConfig
from inorbit_mir_connector.src.connector import MirConnector


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
            connector_type="mir",
            connector_config={
                "mir_username": "user",
                "mir_password": "pass",
                "mir_api_version": "v2.0",
            },
            user_scripts_dir=tmp_path,
            fleet=[
                {
                    "robot_id": "mir100-1",
                    "mir_model": "MiR100",
                    "mir_host_address": "example.com",
                    "mir_host_port": 80,
                    "mir_use_ssl": False,
                    "mir_firmware_version": "v2",
                    "enable_temporary_mission_group": True,
                }
            ],
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


def test_metrics_endpoint_serves_all_metric_families(metrics_connector):
    # OpenTelemetry's Prometheus exporter only writes families that have at
    # least one observation, so actually exercise the instruments.
    record_upstream_http_request(
        vendor="mir", method="GET", endpoint="status", duration_seconds=0.123
    )

    url = f"http://127.0.0.1:{metrics_connector._port}/metrics"
    with urllib.request.urlopen(url, timeout=5) as resp:
        assert resp.status == 200
        body = resp.read().decode("utf-8")

    # Framework gauges (registered eagerly in FleetConnector.__init__).
    # The wire-level namespace is the constant ``inorbit_connector``; the
    # connector type rides as a Resource attribute, not in the name.
    assert "inorbit_connector_up" in body
    assert "inorbit_connector_session_connected" in body

    # Canonical upstream-HTTP family.
    assert "inorbit_connector_upstream_http_requests_total" in body
    assert "inorbit_connector_upstream_http_duration" in body
