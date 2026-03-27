#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
IMAGE_NAME="inorbit-neura-connector"
IMAGE_TAG="${1:-latest}"
ARTIFACT_DIR="${PROJECT_DIR}/artifacts"

echo "==> Building ${IMAGE_NAME}:${IMAGE_TAG}"
docker build \
  -t "${IMAGE_NAME}:${IMAGE_TAG}" \
  -f "${SCRIPT_DIR}/Dockerfile" \
  "${PROJECT_DIR}"

mkdir -p "${ARTIFACT_DIR}"
TAR_FILE="${ARTIFACT_DIR}/${IMAGE_NAME}-${IMAGE_TAG}.tar"

echo "==> Saving to ${TAR_FILE}"
docker save "${IMAGE_NAME}:${IMAGE_TAG}" -o "${TAR_FILE}"

echo "==> Done ($(du -h "${TAR_FILE}" | cut -f1))"
echo "    Copy ${TAR_FILE} to the robot and run: bash deploy.sh"
