#!/bin/bash

# This script builds the Docker image for the MIR Connector.
# The image is tagged with the current version of the connector.
# (maintainers only) the image is pushed to the Google Cloud Registry if the --push flag is provided.

CONNECTOR_VERSION=$(grep -oP '(?<=current_version = ")[^"]*' ../.bumpversion.toml)
IMAGE_NAME="us-central1-docker.pkg.dev/inorbit-integrations/connectors/mir_connector:${CONNECTOR_VERSION}"

echo "Building Docker image '$IMAGE_NAME'..."

cd "$(dirname "$0")/../"

docker build -t $IMAGE_NAME -f docker/Dockerfile .

if [ $? -eq 0 ]; then
    echo "Docker image '$IMAGE_NAME' built successfully."
else
    echo "Failed to build Docker image '$IMAGE_NAME'."
    exit 1
fi

if [ "$1" == "--push" ]; then
    docker push $IMAGE_NAME
    if [ $? -eq 0 ]; then
        echo "Docker image '$IMAGE_NAME' pushed successfully."
    fi
fi
