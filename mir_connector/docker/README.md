# MiR Connector Docker Setup

This document provides instructions on how to set up and run the MiR Connector using Docker.

## Prerequisites

- Docker installed on your machine
- Docker Compose installed

## Setup

1. Clone the repository:
    ```sh
    git clone https://github.com/inorbit-ai/inorbit-robot-connectors.git
    cd inorbit-robot-connectors/mir_connector/docker
    ```

2. Build the Docker image:
    ```sh
    ./build.sh
    ```

3. Run the Docker container. e.g.:
    ```sh
    docker run -d --name ${ROBOT_ID}_connector \
        -v $(pwd)/../config/my_fleet.yaml:/config/fleet.yaml \
        --env-file ../config/.env \
        -e ROBOT_ID=$ROBOT_ID \
        mir_connector
    ```

    Secrets are passed as environment variables (the config loader no longer
    expands `${VARS}` in the YAML). Set these in `config/.env`:
    - `INORBIT_API_KEY` — InOrbit account key
    - `INORBIT_MIR_MIR_USERNAME` — maps to `connector_config.mir_username`
    - `INORBIT_MIR_MIR_PASSWORD` — maps to `connector_config.mir_password`

    Any `connector_config` field can be overridden via `INORBIT_MIR_<FIELD>`.

## Manage a robot fleet with Docker Compose

Multiple robot fleets can be easily managed with a combination of one connector configuration file
and one Docker Compose file.

The file `docker-compose.yaml` in this folder provides an example setup for a fleet of two robots. The configuration for each robot is a list entry under `fleet:` in the shared file `my_fleet.yaml`, which is mounted into the container as `/config/fleet.yaml`, the default location for the connector to read the configuration from. Each container selects its robot with `-id` (driven by the `ROBOT_ID` environment variable).

The shared file uses one `connector_config:` block (fleet-shared MiR credentials and `mir_api_version`) plus the connector-wide top-level fields (`inorbit_robot_key`, `metrics`). A robot that needs its own InOrbit Connect key, distinct MiR credentials, or a distinct metrics `bind_port` requires its own config file (a `fleet` of one).

To start the containers, fill the provided template and run the following command:
```sh
CONNECTOR_VERSION='<connector-version>' docker compose up
```
