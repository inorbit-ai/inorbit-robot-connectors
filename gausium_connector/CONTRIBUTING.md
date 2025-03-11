# Contributing

Contributions are welcome, and they are greatly appreciated! Every little bit
helps, and credit will always be given.

> [!IMPORTANT]
> Any contribution that you make to this repository will be under the MIT license, as dictated by that [license](https://opensource.org/licenses/MIT).

## Get Started

For a basic quickstart, follow the instructions in the top level [CONTRIBUTING.md](../CONTRIBUTING.md). For the Gausium Connector specifically, continue reading below.

## Development

To run the Connector locally, follow the instructions in [README](README.md). In order to run the lint and unit tests, the development dependencies must be installed.

```bash
pip install -e .[dev]
```

To run the lint and unit tests, run:

```bash
tox
```

To run the lint and unit tests for a specific Python version, run:

```bash
tox -e py310
```

## Version Bump

> [!NOTE]
> This section is only relevant for maintainers.

To bump the version of the Connector, use the `bump-my-version` tool.

```bash
bump-my-version bump minor
```

To prevent changes from being applied, use

```bash
bump-my-version bump minor --dry-run --verbose
```

## Build and publish the package

> [!NOTE]
> This section is only relevant for maintainers.

> [!WARNING]
> PyPI is not set up for the Gausium Connector yet.

New releases are built and published to PyPi and the Docker repository automatically by GitHub Actions when a new version bump commit is pushed.

> [!IMPORTANT]
> The message of the last commit must contain "Bump version" for the publish job to run. e.g. "Bump version: 1.0.0 -> 1.0.1"

To manually build and publish the package to https://test.pypi.org/, run:

```bash
pip install .[dev] # Install dependencies
python -m build --sdist # Build the package
twine check dist/* # Run checks
twine upload --repository testpypi dist/* # Upload to test PyPI. $HOME/.pypirc should exist and contain the api tokens. See https://pypi.org/help/#apitoken
```

To manually push the Docker image run `./docker/build.sh --push`

![Powered by InOrbit](../assets/inorbit_github_footer.png)
