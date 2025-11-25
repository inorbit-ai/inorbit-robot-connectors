<!--
SPDX-FileCopyrightText: 2025 InOrbit, Inc.

SPDX-License-Identifier: MIT
-->

# Gausium Open Platform Connector Docker Setup

This directory contains the Docker configuration for the Gausium Open Platform Connector.

## Building the Docker Image

Build the Docker image using the provided build script:

```sh
cd docker
./build.sh
```

The script will:
- Read the version from `pyproject.toml`
- Build the image with tags for both the full registry name and a short name
- Optionally push to the registry if `--push` flag is provided (maintainers only)

The built image will be tagged as:
- `us-central1-docker.pkg.dev/inorbit-integrations/connectors/gausium_open_platform_connector:<version>`
- `gausium_connector:<version>` (short name for local use)

## Running a Single Container

### Basic Usage

Run a single connector instance:

```sh
docker run -d --name ${ROBOT_ID}_connector \
    -v $(pwd)/config/example.yaml:/config/fleet.yaml:ro \
    --env-file $(pwd)/config/.env \
    -e ROBOT_ID=my-robot-id \
    gausium_connector:latest
```

**Important:**
- The config file is mounted to `/config/fleet.yaml` (the default location)
- The `ROBOT_ID` environment variable must match a robot configuration in your YAML file
- Environment variables (including API keys) are loaded from `config/.env`

### Custom Configuration File

To use a different config file path or name:

```sh
docker run -d --name ${ROBOT_ID}_connector \
    -v $(pwd)/config/my_config.yaml:/config/my_config.yaml:ro \
    --env-file $(pwd)/config/.env \
    -e ROBOT_ID=my-robot-id \
    -e CONFIG_FILE=/config/my_config.yaml \
    gausium_connector:latest
```

### Using the Published Image

If using the published image from the registry:

```sh
docker run -d --name ${ROBOT_ID}_connector \
    -v $(pwd)/config/example.yaml:/config/fleet.yaml:ro \
    --env-file $(pwd)/config/.env \
    -e ROBOT_ID=my-robot-id \
    us-central1-docker.pkg.dev/inorbit-integrations/connectors/gausium_open_platform_connector:1.0.9
```

Replace `1.0.9` with the desired version.

## Running Multiple Containers (Docker Compose)

For deploying multiple robot connectors, use Docker Compose. See the [`examples/README.md`](examples/README.md) for a complete deployment example with multiple robots.

Quick start:
```sh
cd docker/examples
cp example.env .env
cp ../config/example.yaml fleet.yaml
# Edit .env and fleet.yaml with your configuration
./run.sh
```

## Configuration

### Environment Variables

- `ROBOT_ID` (required): The InOrbit robot ID that matches a configuration section in your YAML file
- `CONFIG_FILE` (optional): Path to the configuration file inside the container (defaults to `/config/fleet.yaml`)
- `INORBIT_API_KEY`: Your InOrbit API key (can be set in `.env` file)
- `INORBIT_GAUSIUM_CLIENT_ID`: Gausium Open Platform client ID (can be set in `.env` file)
- `INORBIT_GAUSIUM_CLIENT_SECRET`: Gausium Open Platform client secret (can be set in `.env` file)
- `INORBIT_GAUSIUM_ACCESS_KEY_SECRET`: Gausium Open Platform access key secret (can be set in `.env` file)

### Volume Mounts

- Configuration file: Mount your YAML config file to `/config/fleet.yaml` (or use `CONFIG_FILE` to specify a different path)
- Logs (optional): Mount a directory to `/logs/` to persist logs outside the container

### Network

The connector needs network access to:
- InOrbit API (https://control.inorbit.ai)
- Gausium Open Platform API (https://openapi.gs-robot.com)

No special network configuration is required.

## Troubleshooting

### View Logs

```sh
docker logs ${ROBOT_ID}_connector
docker logs -f ${ROBOT_ID}_connector  # Follow logs
```

### Enter Container

```sh
docker exec -it ${ROBOT_ID}_connector bash
```

### Check Configuration

The connector will validate the configuration on startup. If there are errors, check:
1. The `ROBOT_ID` matches a section in your YAML file
2. Required fields are present in the configuration
3. Environment variables are set correctly (check with `docker exec`)

## See Also

- [Examples directory](examples/README.md) - Complete Docker Compose deployment example
- [Main README](../README.md) - General connector documentation
- [Configuration guide](../config/README.md) - Detailed configuration options
