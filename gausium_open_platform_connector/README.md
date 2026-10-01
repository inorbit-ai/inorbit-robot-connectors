<!--
SPDX-FileCopyrightText: 2026 InOrbit, Inc.

SPDX-License-Identifier: MIT
-->

# InOrbit <> Gausium Open Platform Connector

![Gausium <> InOrbit Connector](../assets/gausium_inorbit_connector_banner.png)

[![Workflow Status](https://github.com/inorbit-ai/inorbit-robot-connectors/actions/workflows/gausium_open_platform_workflows.yml/badge.svg)](https://github.com/inorbit-ai/inorbit-robot-connectors/actions)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/)

InOrbit connector for Gausium robots managed by the
[Gausium Open Platform](https://developer.gs-robot.com/en_US/General%20Introduction) cloud API.
It is a fleet connector: a single process serves all the robots listed in its configuration,
polling the Gausium API with account-scoped credentials and publishing each robot to InOrbit.

Built on the [`inorbit-connector`](https://github.com/inorbit-ai/inorbit-connector-python)
framework.

## Features

- Per-robot pose (map-referenced), odometry and key-values following the canonical
  cleaning-vertical data contract: snake_case keys, SI units, percentages as 0-1, normalized
  enums with `_raw` twins carrying the vendor value (battery, task state, tanks, actuators,
  consumable wear, `mission_status` for platform-side modes, and more)
- Mission tracking: publishes a `mission_tracking` event per robot with canonical mission
  fields (coverage, cleaned area, efficiency, water use, battery use, interruptions,
  `task_outcome` from the vendor end status), enriched with the Gausium task report and its
  coverage map images once the task completes
- On-demand robot maps: map images are fetched from the Gausium API and published when a robot
  reports a pose on an unknown map
- Custom commands to submit cleaning tasks and control tasks and navigation (see
  [Custom commands](#custom-commands))
- Vendor-offline reporting: robots reported offline by Gausium show as offline in InOrbit

## Prerequisites

- Python 3.13 or later and [`uv`](https://github.com/astral-sh/uv)
- An InOrbit account [(free signup)](https://control.inorbit.ai/) and an `INORBIT_API_KEY`
- Gausium Open Platform OAuth credentials: `client_id`, `client_secret` and
  `access_key_secret`. Follow the instructions in the
  [Gausium developer portal](https://developer.gs-robot.com/en_US/General%20Introduction)

## Quick start

```bash
uv sync

# Fleet configuration
cp config/fleet.example.yaml config/fleet.yaml   # edit: list your robots
cp config/example.env config/.env                # edit: credentials

# Run
uv run gausium-open-platform-connector -c config/fleet.yaml
```

The `config/.env` file is loaded automatically if present.

## Configuration reference

Top level (see [`config/fleet.example.yaml`](config/fleet.example.yaml)):

| Field | Description |
|-------|-------------|
| `location_tz` | Timezone of the robots' location |
| `connector_type` | Must be `gausium_open_platform` |
| `update_freq` | Publish rate and status poll pacing in Hz. The poll period is `max(fleet status read, 1/update_freq)` |
| `connector_config` | Gausium API settings (below) |
| `fleet` | List of robots to manage |
| `metrics` | Prometheus endpoint for connector and API health (see [Monitoring](#monitoring)) |

`connector_config` fields (each can also be set via the environment with the
`INORBIT_GAUSIUM_OPEN_PLATFORM_` prefix, e.g. `INORBIT_GAUSIUM_OPEN_PLATFORM_CLIENT_ID`):

| Field | Default | Description |
|-------|---------|-------------|
| `base_url` | `https://openapi.gs-robot.com/` | Gausium Open Platform API URL |
| `client_id` | required | OAuth client ID |
| `client_secret` | required | OAuth client secret |
| `access_key_secret` | required | OAuth access key secret |
| `map_resolution` | `0.05` | Map resolution in meters per pixel, used for both the pose conversion and the published map image |
| `mission_success_percentage_threshold` | `0.9` | Cleaned-area ratio at which a mission is reported successful |

Each `fleet` entry:

| Field | Description |
|-------|-------------|
| `robot_id` | InOrbit robot ID. Contact [support@inorbit.ai](mailto:support@inorbit.ai) for a robot ID pool for production fleets |
| `serial_number` | Robot serial number in the Gausium Open Platform (unique) |

## Custom commands

Exposed as InOrbit actions (see [`cac/actions.yaml`](cac/actions.yaml)):

| Script | Arguments | Description |
|--------|-----------|-------------|
| `submit_task` | `area_id`, `cleaning_mode` (`CLEAN`, `SWEEP`, `DUST`, `VACUUM`) | Start a cleaning task on an area of the robot's current map |
| `task_command` | `command` (`PAUSE_TASK`, `RESUME_TASK`, `STOP_TASK`) | Control the currently executing task |
| `navigate` | `command` (`CROSS_NAVIGATE`, `PAUSE_NAVIGATE`, `RESUME_NAVIGATE`, `STOP_NAVIGATE`), `position` | Remote navigation to a named position on the current map |

Apply the configuration-as-code objects in [`cac/`](cac/README.md) to enable these actions and
the rest of the InOrbit experience (data sources, mission tracking, footprint).

## Docker

```bash
cp docker/docker-compose.example.yaml docker/docker-compose.yaml
cp config/example.env config/.env      # fill in credentials
# edit docker-compose.yaml volume paths to point at your fleet config
docker compose -f docker/docker-compose.yaml up -d
```

Images are published to
`us-central1-docker.pkg.dev/inorbit-integrations/connectors/gausium_open_platform_connector`
on version bumps. `docker/build.sh` builds (and optionally pushes) the image locally.

## Monitoring

With `metrics.enabled` the connector serves Prometheus metrics on `metrics.bind_port`
(9090 by default):

- connector health: process up, per-robot session status, execution loop ticks and errors
- Gausium API requests, errors and latency, per endpoint
- `inorbit_connector_gausium_open_platform_status_poll_duration_seconds`: how long one read
  of the whole fleet's status takes, for each of the two status endpoints

That last one sets how often robot data can change. The fleet is read in concurrent chunks,
so the API latency metric covers one chunk, not the full read.

## Development

```bash
uv sync --extra dev
uv run tox           # ruff + pytest with coverage
uv run ruff check    # lint only
```

Releases: `make bump` (see [CONTRIBUTING.md](CONTRIBUTING.md)). The publish workflow triggers on
commit messages matching "Bump gausium-open-platform-connector version".

## Migrating from 1.x

Version 2.0.0 is a rewrite as a fleet connector:

- One connector process now serves the whole fleet. Run a single instance with a `fleet` list
  instead of one process per robot.
- Config format changed: `connector_type` is now `gausium_open_platform` (was the robot model
  name), robots are listed under `fleet` with `robot_id` and `serial_number`, and the
  environment variable prefix is `INORBIT_GAUSIUM_OPEN_PLATFORM_*` (was `INORBIT_GAUSIUM_*`).
  See [`config/fleet.example.yaml`](config/fleet.example.yaml).
- The `total_traveled_distance` and `total_operation_time` key-values were dropped: the
  upstream endpoint feeding them is broken and returned zeros.
- Every published key name changed to the canonical cleaning-vertical contract (see
  [`docs/specs/2026-08-20-canonical-cleaning-datasources.md`](docs/specs/2026-08-20-canonical-cleaning-datasources.md)):
  the raw vendor status is no longer splatted into the key-values, `battery_percentage`
  became `battery_pct` (0-1), and mission report data uses snake_case SI-unit fields.
  Reapply [`cac/`](cac/README.md) and update any account config referencing the old keys,
  including the tag-level derived datasource previously feeding robot modes, which is
  replaced by the connector-published `mission_status` key.

## Contributing

Contributions are made under the MIT [license](https://opensource.org/licenses/MIT).
See [CONTRIBUTING.md](CONTRIBUTING.md).

![Powered by InOrbit](../assets/inorbit_github_footer.png)
