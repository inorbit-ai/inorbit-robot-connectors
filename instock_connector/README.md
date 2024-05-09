# Instock <> InOrbit Connector


|   OS   |                                                                                                                                                                      Python 3.10                                                                                                                                                                      |                                                                                                                                                                      Python 3.11                                                                                                                                                                      |
|:------:|:-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------:|:-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------:|
| Linux  | [![TeamCity](https://inorbit.teamcity.com/app/rest/builds/buildType:id:Engineering_Development_Connectors_InorbitInstockConnector_LinuxPython310QualityCheck/statusIcon.svg)](https://inorbit.teamcity.com/buildConfiguration/Engineering_Development_Connectors_InorbitInstockConnector_LinuxPython310QualityCheck?branch=%3Cdefault%3E&mode=builds) | [![TeamCity](https://inorbit.teamcity.com/app/rest/builds/buildType:id:Engineering_Development_Connectors_InorbitInstockConnector_LinuxPython311QualityCheck/statusIcon.svg)](https://inorbit.teamcity.com/buildConfiguration/Engineering_Development_Connectors_InorbitInstockConnector_LinuxPython311QualityCheck?branch=%3Cdefault%3E&mode=builds) |
| Qodana |    [![TeamCity](https://inorbit.teamcity.com/app/rest/builds/buildType:id:Engineering_Development_Connectors_InorbitInstockConnector_QodanaLinuxQualityCheck/statusIcon.svg)](https://inorbit.teamcity.com/buildConfiguration/Engineering_Development_Connectors_InorbitInstockConnector_QodanaLinuxQualityCheck?branch=%3Cdefault%3E&mode=builds)    |                                                                                                                                                                          --                                                                                                                                                                           |


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

2. From source: clone the repository and install the dependencies:

```bash
cd instock_connector/
virtualenv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Configure the Connector:

- Copy [`config/myinstock.example.yaml`](config/myinstock.example.yaml) and modify the settings to match your setup.

- Copy [`config/example.env`](config/example.env) to `config/.env` and set the environment variables following the instructions in the same
  file. You can get the `INORBIT_KEY` for your account from InOrbit's
  [Developer Console](https://developer.inorbit.ai/docs#configuring-environment-variables).

- Also apply the Configuration as Code manifests under the [cac_examples](cac_examples) folder, through the
  [InOrbit CLI](https://developer.inorbit.ai/docs#using-the-inorbit-cli).

## Deployment

### Run the Connector manually

Once all dependencies are installed and the configuration is complete, the Connector can be run as a Python script. The entry point is `inorbit_instock_connector/src/main.py`.

```bash
# Add the environment variables, activate the virtual environment and run the Connector
cd instock_connector/
export $(grep -v '^#' config/.env | xargs) && \
source .venv/bin/activate && \
python inorbit_instock_connector/src/main.py --help
```

A [script](scripts/start.sh) was provided to help run the Connector.

```
$ ./instock_connector/scripts/start.sh
Usage: ./instock_connector/scripts/start.sh <config_basename>.<robot_id> [<args>]
example: `./instock_connector/scripts/start.sh local.instock-asrs-1 -v` runs the connector with the 'config/local.yaml' configuration and the arguments '-r instock-asrs-1 -v'
The script will start the InOrbit Instock Connector with the specified YAML configuration and robot from the config directory. Extra arguments will be passed to the connector.
Available configurations:
myinstock.example
```

### Run the Connector as a service

To run the Connector as a service, you can use the provided systemd service file. It can be installed by running [`scripts/install_service.sh`](scripts/install_service.sh).

Example: create a service named `instock-connector.myinstock.example.instock-asrs-1` that runs the Connector with `config/myinstock.example.yaml` as a config file and the robot ID `instock-asrs-1`:

```bash
./instock_connector/scripts/install_service.sh myinstock.example.instock-asrs-1
```

The service can be enabled at boot and started with

```bash
sudo systemctl enable instock-connector.<config_basename>.<robot_id>.service
sudo systemctl start instock-connector.<config_basename>.<robot_id>.service
```

## Next Steps

A few areas of improvement in our feature-set include:

- Multi-order status tracking - currently we list a "latest order" sent through the connector
- Add [articles](https://instock.com/en/docs/api/#tag/Articles) as a data-source
- Add [article movements](https://instock.com/en/docs/api/#tag/Moves) as a data-source

If you'd like to contribute, please see [CONTRIBUTING.md](CONTRIBUTING.md) for more information!
