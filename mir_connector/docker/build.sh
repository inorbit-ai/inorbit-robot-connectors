#!/bin/bash

# This script builds the Docker image for the MIR Connector.
# The image is tagged with the current version of the connector.

# (maintainers only) the image is pushed to the Google Cloud Registry if the --push flag is provided.
# Remember to first run `gcloud auth configure-docker us-central1-docker.pkg.dev` to authenticate
# with the Google Cloud Registry.

# Exit on error
set -e

CONNECTOR_VERSION=$(grep -oP '(?<=current_version = ")[^"]*' ../.bumpversion.toml)

IMAGE_NAME="us-central1-docker.pkg.dev/inorbit-integrations/connectors/mir_connector:${CONNECTOR_VERSION}"
IMAGE_NAME_SHORT="mir_connector:${CONNECTOR_VERSION}"

echo "Building Docker image '$IMAGE_NAME'..."

cd "$(dirname "$0")/../"

docker build -t $IMAGE_NAME -t $IMAGE_NAME_SHORT -f docker/Dockerfile .

if [ "$1" == "--push" ]; then
    docker push $IMAGE_NAME
fi
