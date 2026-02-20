<!--
SPDX-FileCopyrightText: 2026 InOrbit, Inc.

SPDX-License-Identifier: MIT
-->

# Contributing

Contributions are encouraged, and they are greatly appreciated! Every little bit helps, and credit will always be given.

> [!IMPORTANT]
> Any contribution that you make to this repository will be under the MIT license, as dictated by that [license](https://opensource.org/licenses/MIT).

## Get Started

Ready to contribute? Here's how to set up `flowcore-connector` for local development.

1. Fork the `flowcore-connector` repo on [GitHub](https://github.com/inorbit-ai/flowcore-connector).

2. Clone your fork locally:

   ```bash
   git clone git@github.com:{your_username_here}/flowcore-connector.git
   ```

3. Install the project in editable mode using [`uv`](https://github.com/astral-sh/uv):

   ```bash
   cd flowcore-connector
   uv sync --extra dev
   ```

   **Maintainers only:**

   To upgrade dependencies to the latest compatible versions, run:
   ```bash
   uv sync --upgrade
   ```

4. Create a branch for local development:

   ```bash
   git checkout -b {your_development_type}/short-description
   ```

   Ex: feature/read-tiff-files or bugfix/handle-file-not-found<br>
   Now you can make your changes locally.

5. When you're done making changes, check that your changes pass linting and tests with tox:

   ```bash
   uv run tox
   ```

6. Commit your changes and push your branch to GitHub:

   ```bash
   git add .
   git commit -m "Resolves #xyz. Your detailed description of your changes."
   git push origin {your_development_type}/short-description
   ```

7. Submit a pull request through the [GitHub](https://github.com/inorbit-ai/flowcore-connector/pulls) website.

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

Releases use `uv version --bump`, which updates both `pyproject.toml` and `uv.lock`.

To release a new version:

1. Ensure you're on the latest `main` branch and working tree is clean:

   ```bash
   git checkout main
   git pull
   ```

2. Use the Make target to bump and tag. Default is `patch`; shortcuts exist (`make bump-patch`, `make bump-minor`, `make bump-major`). Add `DRY=1` to preview without committing/tagging. Add `DIRTY=1` if you intentionally want to allow a dirty working tree (not recommended):

   ```bash
   make bump PART=patch
   # or shortcuts
   make bump-patch
   make bump-minor
   make bump-major
   # dry-run example
   make bump DRY=1 PART=minor
   # allow dirty tree (avoid unless you know why)
   make bump DIRTY=1 PART=patch
   ```

3. Push the commit and the tag:

   ```bash
   git push
   git push --tags
   ```

1. > [!IMPORTANT]
> The message of the last commit must match the configured pattern, e.g. "Bump inorbit-omron-connector version: 0.1.0 → 0.1.1", for the publish job to run.

New releases are built and published to the Docker repository automatically by GitHub Actions when a new version bump commit is pushed.

To manually build and push the Docker image, run:

```bash
./docker/build.sh --push
```

CI automatically publishes to PyPI when either:

- A tag is pushed, or
- A commit message contains "Bump version"

After publishing to PyPI, CI also signs the artifacts and creates/updates the GitHub Release.
