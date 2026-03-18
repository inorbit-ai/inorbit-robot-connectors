# NEURA InOrbit Connector

Bridges NEURA robots (MAV) with [InOrbit](https://www.inorbit.ai/).

```
NEURA MAV  <──fastdds──>  NeuraConnector  <──MQTT──>  InOrbit Cloud
```

## Quick Start

### 1. Prerequisites

Place the `nexus_amr_api` wheel in `artifacts/`:

```
artifacts/nexus_amr_api-1.0.0-cp312-cp312-linux_x86_64.whl
```

### 2. Create config

```bash
cp config/robot.yaml config/robot.yaml
nano config/robot.yaml
```

Key fields:

| Field | Description |
|-------|-------------|
| `robot_ip` | MAV IP address |
| `client_ip` | This machine's IP (reachable by the MAV) |
| `inorbit_api_key` | InOrbit Edge SDK API key |

### 3a. Run with Docker (recommended)

```bash
cd docker
docker compose up -d
docker compose logs -f
docker compose restart
docker compose exec neura-connector bash
```

### 3b. Run locally

```bash
pip install artifacts/nexus_amr_api-*.whl
pip install -e .
python3 -m inorbit_neura_connector.inorbit_neura_connector -c config/robot.yaml
```

## Telemetry (Robot -> InOrbit)

| Data | Description |
|------|-------------|
| 2D Pose (x, y, theta) | via pose2d streaming callback |
| Odometry (speed) | yes |
| Battery (%, voltage) | yes |
| State (id, text) | yes |
| Position confidence | yes |
| Route / error / e-stop flags | yes |
| Map (ROS YAML + image) | yes |

## Commands (InOrbit -> Robot)

| Action | Command | Arguments |
|--------|---------|-----------|
| Drive to point | `drive_to` | `--point_id <id>` |
| Abort drive | `abort_drive` | — |
| Pause / Resume | `pause_drive` / `resume_drive` | — |
| Extend lifting | `extend_lifting` | — |
| Retract lifting | `retract_lifting` | — |
| Reset | `reset` | — |

## Missions

Multi-step missions are sent as a single `executeMissionAction` command. The connector
executes each action in sequence and reports progress back to InOrbit.

### Mission definition

```json
{
  "name": "Delivery Run",
  "actions": [
    {"type": "drive_to", "params": {"point_id": 5}, "on_failure": "abort"},
    {"type": "extend_lifting", "on_failure": "retry", "max_retries": 3, "retry_delay": 5},
    {"type": "drive_to", "params": {"point_id": 12}},
    {"type": "retract_lifting"}
  ]
}
```

### Per-action failure strategies

| `on_failure` | Behavior |
|-------------|----------|
| `abort` (default) | Stop mission immediately, report error |
| `retry` | Retry up to `max_retries` (default 3) with `retry_delay` seconds (default 5) between attempts, then abort |

### Mission commands

| Command | Arguments | Description |
|---------|-----------|-------------|
| `executeMissionAction` | `missionId`, `missionDefinition` (JSON), `missionArgs` (JSON) | Start a mission |
| `cancelMissionAction` | `missionId` | Abort the running mission |
| `updateMissionAction` | `action` (`pause` / `resume`) | Pause or resume |

## Project Structure

```
neura_connector/
├── artifacts/
│   └── nexus_amr_api-*.whl              # AMR Python SDK wheel
├── config/
│   ├── robot.yaml                        # your config
│   └── mav_config.json                   # neurapy_mav config (optional)
├── maps/
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yaml
├── inorbit_neura_connector/
│   ├── __init__.py
│   ├── inorbit_neura_connector.py        # CLI entry point
│   ├── config/
│   │   └── connector_model.py            # RobotConfig + validation
│   └── src/
│       ├── connector.py                  # Main connector
│       ├── mission_executor.py           # Multi-step mission engine
│       ├── nexus_python_api.py           # MAV backend 1 (default)
│       ├── nexus_rest_api.py             # MAV backend 2 (alternative)
│       ├── neurapy_mav_api.py            # MAV backend 3 (alternative)
│       └── grpc_coupler_api.py           # gRPC backend (parked)
├── setup.py
└── README.md
```
