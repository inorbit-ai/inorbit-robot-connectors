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

3. Run the Docker container:
    ```sh
    docker run -d --name ${ROBOT_ID}_connector \
        -v /path/to/your/config.yaml:/config/config.yaml \
        -e ROBOT_ID=$ROBOT_ID \
        mir_connector
    ```

## Manage a robot fleet with Docker Compose

Multiple robot fleets can be easily managed with a combination of one connector configuration file
and one Docker Compose file.

The file `docker-compose.yaml` in this folder provides an example setup for a fleet of two robots. The configuration for each robot is in the shared file `my_fleet.yaml`, which is mounted into the container as `/config/fleet.yaml`, the default location for the connector to read the fleet configuration from.
