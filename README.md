# InOrbit Edge Connectors

![InOrbit Edge Connectors](assets/inorbit_edge_connectors_banner.png)

This repository hosts a collection of Connectors that communicate with the *InOrbit Platform* on behalf of robots by means of the [InOrbit Python Edge SDK](https://github.com/inorbit-ai/edge-sdk-python). Its goal is to group ready to use Connectors for different robot vendors or types, easing the integration between *InOrbit* and any other robot software.

## Connectors

The following Connectors are included in this repository:

### OTTO Motors

The [InOrbit](https://inorbit.ai/) Connector for [OTTO Motors](https://directory.inorbit.ai/connect/OTTO-Motors) AMRs. Making use of the OTTO Fleet Manager's WebSocket and REST APIs, it allows integrating OTTO robots with your fleet on InOrbit, unlocking interoperability.

A single instance of the Connector is capable of controlling multiple robots.

Check the [README](otto_connector/README.md) for more details on requirements and how to set it up.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for information related to developing the code.

![Powered by InOrbit](assets/inorbit_github_footer.png)
