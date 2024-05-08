# Instock <> InOrbit Connector

## Overview

This repository contains the [InOrbit](https://inorbit.ai/) Robot Connector for the [Instock](https://instock.com) ASRS.
Making use of Instock [REST API](https://instock.com/en/docs/api/) and InOrbit's
[Edge SDK](https://developer.inorbit.ai/docs#edge-sdk), the Connector allows the integration of Instock ASRS with your
fleet on InOrbit, unlocking interoperability.

A single instance of the Connector is capable of controlling an entire Instock ASRS.

## Features

By integrating InOrbit's Python Edge SDK with Instock's API, the Connector unlocks the following key features on
InOrbit's platform:

- Visualizing: Grid configuration, status, current pick, etc.
- Picking Actions from the ASRS
- Camera feed integration (optional)

## Requirements

- Python 3.10 or later
- InOrbit account [(it's free to sign up!)](https://control.inorbit.ai)
- Instock API account

## Setup

There are two ways for installing the connector Python package.

1. From PyPi: `pip install inorbit-instock-connector`

2. From source: clone the repository and run `pip install -e instock_connector/`

Configure the Connector:

- Copy `[config/myinstock.example.yaml](config%2Fmyinstock.example.yaml)` and modify the settings to match your setup.

- Copy `config/example.env` to `config/.env` and set the environment variables following the instructions in the same
  file. You can get the `INORBIT_KEY` for your account from InOrbit's
  [Developer Console](https://developer.inorbit.ai/docs#configuring-environment-variables).

- Also apply the Configuration as Code manifests under the [cac_examples](cac_examples) folder, through the
  [InOrbit CLI](https://developer.inorbit.ai/docs#using-the-inorbit-cli).

## Next Steps

A few areas of improvement in our feature-set include:

- Multi-order status tracking - currently we list a "latest order" sent through the connector
- Add [articles](https://instock.com/en/docs/api/#tag/Articles) as a data-source
- Add [article movements](https://instock.com/en/docs/api/#tag/Moves) as a data-source

If you'd like to contribute, please see [CONTRIBUTING.md](CONTRIBUTING.md) for more information!