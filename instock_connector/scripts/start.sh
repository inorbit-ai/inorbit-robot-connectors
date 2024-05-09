#!/bin/bash

# Get script directory
SCRIPT_PATH=`readlink -f $0`
SCRIPT_DIR=`dirname $SCRIPT_PATH`
# Change to the connector directory
cd $SCRIPT_DIR/..

if [ -z "$1" ]; then
    echo "Usage: $0 <config_basename>.<robot_id> [<args>]"
    echo "example: \`$0 local.instock-asrs-1 -v\` runs the connector with the 'config/local.yaml' configuration and the arguments '-r instock-asrs-1 -v'"
    echo "The script will start the InOrbit Instock Connector with the specified YAML configuration and robot from the config directory. Extra arguments will be passed to the connector."
    echo "Available configurations:"
    ls config/*.yaml | xargs -n 1 basename | sed 's/\.yaml//'
    exit 1
fi

# Parameters
ENV_FILE=config/.env
VENV_DIR=.venv
ROBOT_ID=`echo $1 | rev | cut -d. -f1 | rev`  # Get last column
FILE_BASENAME=`echo $1 | rev | cut -d. -f2- | rev`  # Get all but last column (allowing for file basenames with dots)
CONFIG_FILE=config/$FILE_BASENAME.yaml
CONNECTOR_ARGS="-r $ROBOT_ID ${@:2}"
CONNECTOR_SCRIPT=inorbit_instock_connector/src/main.py

if [ ! -f $CONFIG_FILE ]; then
    echo "Configuration file $CONFIG_FILE not found"
    exit 1
fi

# Activate the virtual environment
source $VENV_DIR/bin/activate
# Get all environment variables from the .env file and export them
export $(grep -v '^#' $ENV_FILE | xargs)
# Start the connector
python $CONNECTOR_SCRIPT -c $CONFIG_FILE $CONNECTOR_ARGS
