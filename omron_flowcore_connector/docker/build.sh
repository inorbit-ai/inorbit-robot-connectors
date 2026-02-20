#!/bin/bash

# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

# This script builds the Docker image for the FLOWCore Connector.
# The image is tagged with the current version of the connector.

# (maintainers only) the image is pushed to the Google Cloud Registry if the --push flag is provided.
# Remember to first run `gcloud auth configure-docker us-central1-docker.pkg.dev` to authenticate
# with the Google Cloud Registry.

# Please note that for release purposes GitHub workflows will build and push the image automatically
# on version bumps.

# Exit on error
set -e

REPO_ROOT_DIR="$(dirname "$0")/.."

IMAGE_NAME="us-central1-docker.pkg.dev/inorbit-integrations/connectors/flowcore_connector"
IMAGE_NAME_SHORT="flowcore_connector"

echo "Building Docker image '$IMAGE_NAME'..."

cd "$REPO_ROOT_DIR"

set +e
CONNECTOR_VERSION=$(
python3 - <<'PY'
import pathlib
import tomllib

pyproject = pathlib.Path("pyproject.toml")
data = tomllib.loads(pyproject.read_text())
print(data["project"]["version"])
PY
)
if [ $? -ne 0 ]; then
    CONNECTOR_VERSION="latest"
fi
set -e

docker build \
    -t $IMAGE_NAME:latest \
    -t $IMAGE_NAME:$CONNECTOR_VERSION \
    -t $IMAGE_NAME_SHORT:latest \
    -t $IMAGE_NAME_SHORT:$CONNECTOR_VERSION \
    -f docker/Dockerfile .

if [ "$1" == "--push" ]; then
    docker push $IMAGE_NAME:$CONNECTOR_VERSION
fi