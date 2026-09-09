<!--
SPDX-FileCopyrightText: 2026 InOrbit, Inc.

SPDX-License-Identifier: MIT
-->

# InOrbit FLOWCore Connector

[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/)

InOrbit Edge connector for FLOWCore

## Overview

This repository contains the [InOrbit](https://inorbit.ai/) Edge Connector for [Omron](https://automation.omron.com/) AMRs connected to FLOWCore.

This integration requires the Connector to be configured following the instructions below.

## Features

- Multi-robot fleet management through a single connector instance
- Real-time robot monitoring (pose, battery, state, velocity, etc.)
- Automatic retry logic with exponential backoff for API calls
- Background polling architecture for efficient data fetching
- Annotation synchronization for waypoint positions between FLOWCore and InOrbit
- Built on top of the [`inorbit-connector-python`](https://github.com/inorbit-ai/inorbit-connector-python) framework

## Requirements

- Python 3.13 or later
- InOrbit account [(it's free to sign up!)](https://control.inorbit.ai/)
- Access to a FLOWCore server with API credentials
- Network connectivity between the connector host and FLOWCore server

## Setup

1. Create a Python virtual environment in the host machine and install the connector.

```shell
# Using uv (recommended)
uv sync
```

> [!TIP]
> Installing the `colorlog` package is optional. If available, it will be used to colorize the logs.

```shell
uv pip install colorlog
```

2. Configure the Connector:

- Copy `config/fleet.example.yaml` to `config/my_fleet.yaml` and configure your robot fleet. Each robot needs an InOrbit `robot_id` and the corresponding FLOWCore `fleet_robot_id`.

- Optionally, configure the FLOWCore connector-specific settings via environment variables. Copy `config/example.env` to `config/.env` and fill in the values. Any `connector_config` fields can be set using the `INORBIT_FLOWCORE_` prefix (e.g., `INORBIT_FLOWCORE_URL`, `INORBIT_FLOWCORE_PASSWORD`). Environment variables are used as fallbacks when fields are missing from the YAML configuration. See `config/example.env` for reference. The `.env` file will be automatically loaded when the connector is run.

- Set the `INORBIT_API_KEY` environment variable. You can get the API key for your account from InOrbit's [Developer Console](https://developer.inorbit.ai/docs#configuring-environment-variables).

```bash
export INORBIT_API_KEY=your-api-key-here
# Or place the value in the config/.env file
```

## Deployment

Once all dependencies are installed and the configuration is complete, the Connector can be run as a command.

```bash
source config/.env && uv run inorbit-omron-connector -c config/my_fleet.yaml
```

### Docker

The Connector can be run as a containerized application using Docker Compose:

1. Copy `docker/docker-compose.example.yaml` to `docker/docker-compose.yaml`
2. Copy `config/example.env` to `config/.env` and fill in your credentials
3. Update volume paths in `docker-compose.yaml` to point to your configuration files
4. Run: `docker compose -f docker/docker-compose.yaml up -d`

The Docker Compose setup supports environment variable configuration via `config/.env` and allows running multiple connector instances. See `docker/docker-compose.example.yaml` for detailed configuration options.

## Metrics (optional)

The connector can expose Prometheus-format metrics so fleet operators can monitor connector health. Metrics are off by default and add no overhead until enabled.

Enable via the top-level `metrics:` block in your fleet YAML (connector-wide, not per-robot):

```yaml
metrics:
  enabled: true
  bind_host: 0.0.0.0
  bind_port: 9090
  discovery_dir: null   # set to a writable dir to use Prometheus file_sd
```

Then scrape with `curl http://localhost:9090/metrics`.

Exported metrics include connector liveness (`inorbit_connector_up`), per-robot InOrbit session status (`inorbit_connector_session_connected`), execution loop ticks/errors, and the upstream FlowCore API request/error/latency family (`inorbit_connector_upstream_http_*` with `vendor="flowcore"`). All metrics share the `inorbit_connector` wire prefix; the connector type rides on every series as a resource attribute rather than in the metric name.

## Robot availability

A robot is reported online to InOrbit while the Fleet Manager has fetched a DataStore value from it within the grace window. That is the whole rule. `/DataStoreValueLatest` reaches the AMR on every call (Integration Toolkit manual, p.23: it "obtains the latest value from the entity in question"), so a value coming back is the Fleet Manager saying it just reached the robot, and a robot it cannot reach returns nothing. Availability is measured, not read off a status label.

The grace window is three missed polls, with a floor of 10 seconds: both poll loops run at `update_freq`, the Fleet Manager takes up to 10 seconds to reflect an attach or detach, and a wildcard `/DataStoreValueLatest` fetch takes about 2 seconds by design. There is no knob for it, since the only meaning a grace can have is missed polls and a value set without knowing the poll period can keep every robot offline between successful polls. Both clocks are seeded at startup so a connector start or restart is not reported as an offline transition while the first polls are in flight.

The status vocabulary explains an offline robot, it does not decide it. `OutgoingArclConnectionLost` in particular does not mean the robot is unreachable: a live Fleet Manager kept fetching battery and pose from a robot carrying that sub-status for hours while the robot answered ICMP and accepted connections on its ARCL port. "Outgoing" is literal, the Fleet Manager's own command channel is down. That robot is online with `status: ERROR`, because FlowCore cannot dispatch to it, and its live pose is what you need to go find it. The same holds for a robot that is reachable but faulted (`Fault`, `Lost`, `EstopPressed`, `MotorsDisabled`). `Disconnected`, an undocumented value found by probing a live Fleet Manager rather than in Rev C of the manual, is what FlowCore reports once it has given up on a robot, and such a robot returns no DataStore values at all, so the two signals agree; if they ever disagree, the fetch wins.

Presence in the `/Robot/UpdatedSince` listing is fleet membership, not reachability: the Integration Toolkit reflects a robot being added to or removed from the fleet within 10 seconds, but a robot that has lost communication stays listed until somebody deregisters it, observed at 17 days on a live Fleet Manager. It is published as `robot_attached` and used only to explain an offline robot as `not_in_fleet`.

Publishes are gated so a value is sent when it changed, not on every tick, and the gate differs by endpoint because the endpoints stamp differently. `/Robot/UpdatedSince` is a changed-since query, so a summary's `upd.millis` holds while its status is unchanged (observed frozen at 17 days and at 4 hours across paired polls) and is a genuine change token. `/DataStoreValueLatest` stamps each fetch, so a DataStore item's `upd.millis` is the connector's own read time and advances on every poll whatever the value did; those items are compared by value instead. Mission tracking has neither, since the Job and JobSegment streams carry no `upd.millis`, so it publishes only when the mission payload itself changes. Key-values publish in three tiers: health (`connector_version`, `api_connected`, `robot_attached`) is the connector's own view and publishes on every execution loop iteration, ungated, so an operator can tell a quiet robot from a broken connector; the fleet summary (`omron_status`, `omron_sub_status`, `status`, `robot_ip`) is FlowCore's own statement and publishes when its `upd.millis` changes while the API is connected, regardless of whether the robot itself is online, since it is what carries a disconnection to InOrbit; robot telemetry (`battery_percent`, pose, odometry) is the robot's own data and publishes when its values change, with no online check on top, since a robot that stops answering stops producing values and the cache holds by itself. `robot_attached` is omitted while `api_connected` is false, since it is not knowable when the connector cannot reach the API. A known trade of gating pose on change: a robot parked longer than 30 seconds exceeds the edge SDK's distance-accumulation window, so the first pose reported after it moves again is not counted toward InOrbit's distance travelled, roughly one tick of travel per stop-start cycle.

## Contributing

Any contribution that you make to this repository will be under the MIT license, as dictated by that [license](https://opensource.org/licenses/MIT).

Please refer to the [CONTRIBUTING.md](CONTRIBUTING.md) file for information on how to contribute to this project.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

## Support

- **Documentation**: [InOrbit Developer Docs](https://developer.inorbit.ai/)
- **Issues**: [GitHub Issues](https://github.com/inorbit-ai/flowcore-connector/issues)
- **Email**: support@inorbit.ai

![Powered by InOrbit](../assets/inorbit_github_footer.png)
