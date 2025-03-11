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
inorbit_gausium_connector -c config/myfleet.example.yaml -id phantas-1
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
