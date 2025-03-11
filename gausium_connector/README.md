<!--
SPDX-FileCopyrightText: 2025 InOrbit, Inc.

SPDX-License-Identifier: MIT
-->

# InOrbit <> Gausium Connector

InOrbit Edge-SDK connector for Gausium robots.

## Features

* TODO

## Installation

```shell
virtualenv venv
source venv/bin/activate
pip install -e .
```

## Configuration

The connector is configured using a YAML file. See `config/` for examples.

## Usage

```bash
inorbit_gausium_connector -c config/example.yaml -id my-example-robot
```

Environment variables will be loaded from `config/.env` if it exists. Otherwise, they can be set manaully.

## Development

```shell
virtualenv venv
source venv/bin/activate
pip install -e .[dev]
# Run tests
tox
```

## Deployment

TODO
