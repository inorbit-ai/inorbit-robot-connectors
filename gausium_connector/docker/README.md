<!--
SPDX-FileCopyrightText: 2025 InOrbit, Inc.

SPDX-License-Identifier: MIT
-->

# Gausium Connector Docker Setup

Build the Docker image:
```sh
# Use --push to upload the image
./build.sh
```

Run the Docker container:
```sh
docker run -d --name ${ROBOT_ID}_connector \
    -v $(pwd)/config/config.yaml:/config/fleet.yaml \
    --env-file $(pwd)/config/.env \
    -e ROBOT_ID=$ROBOT_ID \
    gausium_connector
```
