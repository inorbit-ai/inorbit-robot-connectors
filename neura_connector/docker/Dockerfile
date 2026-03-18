FROM python:3.12-slim

WORKDIR /app

COPY setup.py README.md ./
COPY inorbit_neura_connector/ inorbit_neura_connector/
COPY config/ config/
COPY maps/ maps/
COPY artifacts/*.whl /tmp/wheels/
COPY artifacts/*.deb /tmp/debs/

RUN apt-get update && \
    apt-get install -y --no-install-recommends iputils-ping curl net-tools && \
    dpkg -i /tmp/debs/*.deb || true && \
    apt-get install -f -y && \
    rm -rf /tmp/debs /var/lib/apt/lists/* && \
    pip install --no-cache-dir /tmp/wheels/*.whl && \
    pip install --no-cache-dir . && \
    rm -rf /tmp/wheels

CMD ["python3", "-m", "inorbit_neura_connector.inorbit_neura_connector", "-c", "/app/config/robot.yaml"]
