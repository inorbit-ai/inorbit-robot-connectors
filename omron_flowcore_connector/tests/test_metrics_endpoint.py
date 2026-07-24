# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Integration test for the OTel Prometheus exporter wiring.

Builds a real :class:`OmronConnector` with ``metrics.enabled=True``, starts
the metrics HTTP server, exercises the canonical upstream-HTTP family, then
scrapes ``/metrics`` and asserts the metric families appear under the single
``inorbit_connector`` wire namespace.

OTel's MeterProvider is a process-global singleton, so this test deliberately
runs as a single non-parametrized case.
"""

import socket
import urllib.request
from unittest.mock import MagicMock, patch

import pytest
from inorbit_connector.metrics.http import record_upstream_http_request
from inorbit_edge.robot import RobotSession

from inorbit_omron_connector.src.config.models import FlowCoreConnectorConfig
from inorbit_omron_connector.src.connector import OmronConnector


def _free_port() -> int:
    """Return a free TCP port on localhost."""
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


@pytest.fixture
def metrics_connector(monkeypatch):
    """Build an OmronConnector with metrics enabled on an ephemeral port."""
    monkeypatch.setattr(RobotSession, "connect", MagicMock())
    port = _free_port()

    config = FlowCoreConnectorConfig(
        api_key="test_key",
        connector_type="flowcore",
        connector_config={
            "url": "https://mock.example.com",
            "password": "mock",
            "arcl_password": "mock",
            "use_mock": True,
        },
        fleet=[{"robot_id": "robot-1", "fleet_robot_id": "Robot1_FlowCore"}],
        metrics={
            "enabled": True,
            "bind_host": "127.0.0.1",
            "bind_port": port,
            "discovery_dir": None,
        },
    )

    with patch("inorbit_omron_connector.src.connector.OmronMissionExecutor", autospec=True):
        connector = OmronConnector(config)
    connector._port = port  # stash for the test to scrape

    # Start only the metrics HTTP server; the full connector thread (MQTT,
    # FlowCore polling) is not needed to verify the exporter wiring.
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
        vendor="flowcore", method="GET", endpoint="robot_updated_since", duration_seconds=0.1
    )

    url = f"http://127.0.0.1:{metrics_connector._port}/metrics"
    with urllib.request.urlopen(url, timeout=5) as resp:
        assert resp.status == 200
        body = resp.read().decode("utf-8")

    # Framework gauges (registered eagerly in FleetConnector.__init__).
    assert "inorbit_connector_up" in body
    assert "inorbit_connector_session_connected" in body

    # Canonical upstream-HTTP family.
    assert "inorbit_connector_upstream_http_requests_total" in body
    assert "inorbit_connector_upstream_http_duration" in body
