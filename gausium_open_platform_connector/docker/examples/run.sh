#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

set -e

export CONNECTOR_VERSION="${CONNECTOR_VERSION:-1.0.9}"

if ! command -v docker >/dev/null; then
    echo "Error: command docker not found." >&2
    echo "Follow the instructions on the official site to install docker engine: https://docs.docker.com/engine/install/" >&2
    exit 1
fi

if ! [ -f .env ]; then
    echo "Warning: .env file not found. Please create it from example.env and fill in your credentials." >&2
fi

if ! [ -f fleet.yaml ]; then
    echo "Error: fleet.yaml file not found. Please create it based on the example configuration." >&2
    exit 1
fi

docker compose up -d --remove-orphans

echo
echo "Fleet initiated successfully"
echo
echo "Useful commands:"
echo "  docker compose ps                    - See the status of the fleet"
echo "  docker compose logs -f               - See logs from all services"
echo "  docker compose logs -f <service_name> - See logs from a specific service"
echo "  docker compose exec <service_name> bash - Enter a service container"
echo "  docker compose down                  - Stop the fleet"
echo
echo "To update the fleet without stopping it, edit 'docker-compose.yaml' and then run this script again, or run 'docker compose up -d'"
echo
echo "Current status:"
docker compose ps
