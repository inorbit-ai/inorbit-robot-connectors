# InOrbit <> robot connectors

This repository hosts a collection of connectors that communicate with `InOrbit` platform on behalf of robots by means of the [InOrbit Python Edge SDK](https://github.com/inorbit-ai/edge-sdk-python). It's goal is to group ready to use connectors for different robot vendors or types, easing the integration between `InOrbit` and any other software robot data.

## Connectors

The following connectors are included in this repository:

### OTTO <> InOrbit connector

The [InOrbit](https://inorbit.ai/) connector for [OTTO Motors](https://directory.inorbit.ai/connect/OTTO-Motors) AMRs. Making use of the OTTO Fleet Manager's WebSocket and REST APIs, it allows integrating OTTO robots with your fleet on InOrbit, unlocking interoperability.

A single instance of the Connector is capable of controlling multiple robots.

Check the [README](otto_connector/README.md) for more details on requirements and how to set it up.

## Development

Install [pre-commit](https://pre-commit.com/) in your computer and then set it up by running `pre-commit install` at the root of the cloned project.

See [CONTRIBUTING.md](CONTRIBUTING.md) for information related to developing the code.

![Powered by InOrbit](assets/inorbit_github_footer.png)
