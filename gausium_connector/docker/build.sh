#!/bin/bash

# This script builds the Docker image for the Gausium Connector.
# The image is tagged with the current version of the connector.

# (maintainers only) the image is pushed to the Google Cloud Registry if the --push flag is provided.
# Remember to first run `gcloud auth configure-docker us-west2-docker.pkg.dev to authenticate
# with the Google Cloud Registry.

# Exit on error
set -e

CONNECTOR_VERSION=$(grep -oP '(?<=current_version = )[^"]*' ../setup.cfg)

IMAGE_NAME="us-central1-docker.pkg.dev/inorbit-integrations/connectors/gausium_connector"
IMAGE_NAME_SHORT="gausium_connector"

echo "Building Docker image '$IMAGE_NAME'..."

cd "$(dirname "$0")/../"

docker build \
    -t $IMAGE_NAME:latest \
    -t $IMAGE_NAME:$CONNECTOR_VERSION \
    -t $IMAGE_NAME_SHORT:latest \
    -t $IMAGE_NAME_SHORT:$CONNECTOR_VERSION \
    -f docker/Dockerfile .

if [ "$1" == "--push" ]; then
    docker push $IMAGE_NAME:$CONNECTOR_VERSION
fi
