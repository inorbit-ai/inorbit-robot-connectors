# Use the official Python 3.12 image from the Docker Hub
FROM python:3.12

# Set the working directory in the container
WORKDIR /app

# Copy the application code into the container
COPY . .

# Install the dependencies
RUN pip install -e .

# Set the environment variable for Python to not buffer the output and make sure all information is
# printed to the console. This is useful for troubleshooting crashes and errors.
ENV PYTHONUNBUFFERED=1

# Run the connector.
# The configuration file can be set using the CONFIG_FILE environment variable and will default to /config/fleet.yaml
CMD ["sh", "-c", "inorbit-mir100-connector -c ${CONFIG_FILE:-/config/fleet.yaml} -id $ROBOT_ID"]
