<!--
SPDX-FileCopyrightText: 2025 InOrbit, Inc.

SPDX-License-Identifier: MIT
-->

# InOrbit <> Gausium Open Platform Connector Deployment Example

This directory contains example files for deploying multiple instances of the Gausium Open Platform Connector using Docker Compose.

## Quick Start

1. **Copy the example files:**
   ```bash
   cp example.env .env
   cp ../config/example.yaml fleet.yaml
   ```

2. **Configure your deployment:**
   - Edit `.env` and fill in your credentials:
     - `INORBIT_API_KEY`: Your InOrbit API key (get it from the [Developer Console](https://developer.inorbit.ai/docs#configuring-environment-variables))
     - `INORBIT_GAUSIUM_CLIENT_ID`: Your Gausium Open Platform client ID
     - `INORBIT_GAUSIUM_CLIENT_SECRET`: Your Gausium Open Platform client secret
     - `INORBIT_GAUSIUM_ACCESS_KEY_SECRET`: Your Gausium Open Platform access key secret
   
   - Edit `fleet.yaml` and configure each robot:
     - Update the `serial_number` for each robot
     - Adjust `location_tz` if needed
     - Modify `log_level` if desired

3. **Deploy:**
   ```bash
   ./run.sh
   ```

## Configuration

### docker-compose.yaml

The `docker-compose.yaml` file defines multiple connector instances. Each service represents one robot connector. The file uses:
- A common configuration template (`x-common-deploy-config`) shared by all services
- Individual `ROBOT_ID` environment variables to identify each robot
- A shared `fleet.yaml` configuration file that contains settings for all robots

### fleet.yaml

This file contains the configuration for all robots in your fleet. Each robot is identified by its `robot_id` (which matches the `ROBOT_ID` in docker-compose.yaml). The structure matches the format described in the main [config/README.md](../../config/README.md).

### .env

Contains sensitive credentials that should not be committed to version control. Copy `example.env` to `.env` and fill in your actual credentials.

### run.sh

Helper script that:
- Sets the connector version
- Validates prerequisites
- Starts the Docker Compose services
- Provides helpful commands for managing the fleet

## Managing the Fleet

- **View status:** `docker compose ps`
- **View logs:** `docker compose logs -f` (all services) or `docker compose logs -f <service_name>` (specific service)
- **Stop fleet:** `docker compose down`
- **Update fleet:** Edit `docker-compose.yaml` or `fleet.yaml`, then run `./run.sh` again or `docker compose up -d`

## Customization

- **Add more robots:** Add a new service to `docker-compose.yaml` and add the corresponding configuration to `fleet.yaml`
- **Change connector version:** Set `CONNECTOR_VERSION` environment variable or edit `run.sh`
- **Adjust resource limits:** Modify the `deploy.resources.limits` section in `docker-compose.yaml`
- **Custom log directory:** Update the volume mount for `./logs/` in `docker-compose.yaml`
