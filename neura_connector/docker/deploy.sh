#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
IMAGE_NAME="inorbit-neura-connector"
IMAGE_TAG="${1:-latest}"
ARTIFACT_DIR="${PROJECT_DIR}/artifacts"
TAR_FILE="${ARTIFACT_DIR}/${IMAGE_NAME}-${IMAGE_TAG}.tar"

# --- Load image ---
if [ -f "${TAR_FILE}" ]; then
    echo "==> Loading ${TAR_FILE}"
    docker load -i "${TAR_FILE}"
else
    echo "ERROR: ${TAR_FILE} not found"
    echo "Build first with: bash docker/build.sh"
    exit 1
fi

# --- Start via docker compose ---
echo "==> Starting with docker compose"
cd "${SCRIPT_DIR}"
docker compose down
docker compose up -d

echo "==> Container running"
echo ""
echo "Useful commands:"
echo "  docker compose -f ${SCRIPT_DIR}/docker-compose.yaml logs -f      # view logs"
echo "  docker compose -f ${SCRIPT_DIR}/docker-compose.yaml exec neura-connector bash  # shell in"
echo "  docker compose -f ${SCRIPT_DIR}/docker-compose.yaml restart      # restart after edits"
echo "  docker compose -f ${SCRIPT_DIR}/docker-compose.yaml down         # stop and remove"
