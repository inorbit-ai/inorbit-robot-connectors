# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

# Use the official Python 3.12 image from the Docker Hub
FROM python:3.12-slim

# Set the environment variable for Python to not buffer the output and make sure all information is
# printed to the console. This is useful for troubleshooting crashes and errors.
ENV PYTHONUNBUFFERED=1
# The configuration file can be set using the CONFIG_FILE environment variable and will default to /config/fleet.yaml
ENV DEFAULT_CONFIG_FILE=/config/fleet.yaml

# Set the working directory in the container
WORKDIR /app

# Copy the application code into the container
COPY . .

# Install the connector. The --no-cache-dir flag prevents from caching the downloaded packages,
# reducing image size.
RUN pip install --upgrade --no-cache-dir pip
RUN pip install . --no-cache-dir
ENV PYTHONPATH="/app"

# Run the connector.
# The configuration file can be set using the CONFIG_FILE environment variable and will default to /config/fleet.yaml
CMD ["sh", "-c", "inorbit_gausium_connector -c ${CONFIG_FILE:-${DEFAULT_CONFIG_FILE}} -id $ROBOT_ID"]
