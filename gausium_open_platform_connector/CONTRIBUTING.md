<!--
SPDX-FileCopyrightText: 2025 InOrbit, Inc.

SPDX-License-Identifier: MIT
-->

# Contributing

Contributions are encouraged, and they are greatly appreciated! Every little bit helps, and credit will always be given.

> [!IMPORTANT]
> Any contribution that you make to this repository will be under the MIT license, as dictated by that [license](https://opensource.org/licenses/MIT).

## Get Started

Ready to contribute? Here's how to set up `inorbit_gausium_connector` for local development.

1. Fork the `inorbit-robot-connectors` repo on [GitHub](https://github.com/inorbit-ai/inorbit-robot-connectors).

2. Clone your fork locally:

   ```bash
   git clone git@github.com:{your_username_here}/inorbit-robot-connectors.git
   ```

3. CD into the `gausium_open_platform_connector` directory and create a virtual environment:
   ```bash
   cd gausium_open_platform_connector
   python -m venv venv
   source venv/bin/activate
   ```

4. Install the project in editable mode:

   ```bash
   pip install -e .[dev]
   ```

5. Create a branch for local development:

   ```bash
   git checkout -b {your_development_type}/short-description
   ```

   Ex: feature/read-tiff-files or bugfix/handle-file-not-found<br>
   Now you can make your changes locally.

6. When you're done making changes, check that your changes pass linting and tests with tox:

   ```bash
   tox
   ```

7. Commit your changes and push your branch to GitHub:

   ```bash
   git add .
   git commit -m "Resolves #xyz. Your detailed description of your changes."
   git push origin {your_development_type}/short-description
   ```

8. Submit a pull request through the [GitHub](https://github.com/inorbit-ai/inorbit-robot-connectors/pulls) website.

## Development

To run the Connector locally, follow the instructions in [README](README.md).

To check for REUSE compliance, run:

```bash
reuse --root . lint
```

And to fix REUSE compliance issues, run:

```bash
reuse annotate --copyright "InOrbit, Inc." --license "MIT" --recursive . --skip-unrecognised
```

## Version bump and release - Maintainers only

To release a new version:

1. Ensure you're on the latest `main` branch:

   ```bash
   git checkout main
   git pull
   ```

2. Bump the version using `bump-my-version`. This automatically increments the version number in the
   places specified in the `pyproject.toml` file:

   ```bash
   # Use major, minor, or patch to increment the version number
   bump-my-version patch --dry-run --verbose
   bump-my-version patch
   ```

3. Push both the commit and the tag:

   ```bash
   git push
   git push --tags
   ```

> [!IMPORTANT]
> The message of the last commit must match the configured pattern, e.g. "Bump inorbit_gausium_open_platform_connector version: 0.1.0 → 0.1.1", for the publish job to run.

New releases are built and published to the Docker repository automatically by GitHub Actions when a new version bump commit is pushed.

To manually build and push the Docker image, run:

```bash
./docker/build.sh --push
```
