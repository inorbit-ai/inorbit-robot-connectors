<!--
SPDX-FileCopyrightText: 2025 InOrbit, Inc.

SPDX-License-Identifier: MIT
-->

# Configuration

This directory contains the configuration files for the Phantas connector. Each instance of the connector requires one configuration object, many of which can be stored in a single YAML file indexed by InOrbit robot ID. Some values can also be stored in environment variables.

See [`example.yaml`](example.yaml) and [`example.env`](example.env) for examples of the configuration files.

Optional `connector_config` fields not shown in the example:

| Field | Default | Meaning |
|---|---|---|
| `map_resolution` | `0.05` | Meters per pixel of the robot's map. Converts the reported pose and describes the map image published to InOrbit, so both share one frame. |
| `mission_success_percentage_threshold` | `0.90` | Coverage a normally finished task must reach to be reported as completed rather than incomplete. |
