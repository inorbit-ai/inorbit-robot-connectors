# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

# Reference: https://github.com/astral-sh/uv-docker-example/blob/main/multistage.Dockerfile

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

# Enable bytecode compilation and use copy mode
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Disable Python downloads: we want to use the system interpreter that matches the final image
ENV UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Install only the dependencies using the lockfile.
# README.md is included because it is referenced by pyproject.toml.
COPY pyproject.toml README.md uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev

# Add the project source code and install it.
COPY inorbit_omron_connector/ ./inorbit_omron_connector/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# Must match the Python base used by the uv image above
FROM python:3.13-slim-bookworm

# Set the environment variable for Python to not buffer the output and make sure all information is
# printed to the console. This is useful for troubleshooting crashes and errors.
ENV PYTHONUNBUFFERED=1

# The configuration file can be set using the CONFIG_FILE environment variable and will
# default to /config/fleet.yaml
ENV DEFAULT_CONFIG_FILE=/config/fleet.yaml

# Create directories for persistent data
RUN mkdir -p /app/logs

# Copy the application from the builder image
COPY --from=builder /app /app
COPY config/ /app/config/

# Place executables from the virtual environment at the front of the PATH
ENV PATH="/app/.venv/bin:$PATH"

# Use /app as the working directory
WORKDIR /app

# Run the connector.
# The configuration file can be set using the CONFIG_FILE environment variable and will
# default to /config/fleet.yaml
# Use a shell so that the expansion happens at runtime.
CMD ["sh", "-c", "inorbit-omron-connector -c ${CONFIG_FILE:-${DEFAULT_CONFIG_FILE}}"]
