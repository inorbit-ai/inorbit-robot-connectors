<!--
SPDX-FileCopyrightText: 2023 InOrbit, Inc.

SPDX-License-Identifier: MIT
-->

# MiR ↔ InOrbit Connector

![MiR ↔ InOrbit Connector](../assets/mir_inorbit_connector_banner.png)

[![Workflow Status](https://github.com/inorbit-ai/inorbit-robot-connectors/actions/workflows/mir_workflows.yml/badge.svg)](https://github.com/inorbit-ai/inorbit-robot-connectors/actions)

## Overview

The [InOrbit](https://inorbit.ai/) Robot Connector for [MiR Motors](https://directory.inorbit.ai/connect/Mobile-Industrial-Robots-A/S) AMRs integrates MiR robots with InOrbit's fleet management platform. Using MiR's REST APIs and InOrbit's [Edge SDK](https://developer.inorbit.ai/docs#edge-sdk), this connector enables seamless robot fleet management and monitoring.

**🔧 One Connector Per Robot**: Each MiR robot requires its own connector instance for optimal performance and isolation. The connector supports simplified fleet-wide configuration with per-robot overrides.

## ✨ Features

- **Real-time Monitoring**: Robot pose, system status, battery levels, and error states
- **Camera Integration**: Live video feeds from robot cameras  
- **Mission Control**: Dispatch, pause, cancel missions via [Actions](https://developer.inorbit.ai/docs#configuring-action-definitions)
- **Custom Scripts**: Execute custom shell scripts on the connector via Custom Actions
- **Mission Tracking**: Full [Mission Tracking](https://developer.inorbit.ai/docs#configuring-mission-tracking) support
- **SSL Support**: Secure connections with full certificate validation
- **Multi-Robot Fleet Management**: Simplified configuration for managing multiple robots

## 📋 Requirements

- **Python 3.7+** with SQLite3 support (included in most distributions)
- **InOrbit Account** [(free signup)](https://control.inorbit.ai/)
- **MiR Robot** with REST API access
- **Network Access** between connector host and MiR robot

## 🚀 Quick Start

### 1. Clone and Setup

<details>
<summary><b>🐧 Linux/macOS</b></summary>

```bash
# Clone the repository
git clone https://github.com/inorbit-ai/inorbit-robot-connectors.git
cd inorbit-robot-connectors/mir_connector

# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Verify activation (should show venv path)
which python
```
</details>

<details>
<summary><b>🪟 Windows</b></summary>

```cmd
# Clone the repository
git clone https://github.com/inorbit-ai/inorbit-robot-connectors.git
cd inorbit-robot-connectors/mir_connector

# Create virtual environment
python -m venv venv

# Activate virtual environment
venv\Scripts\activate

# Verify activation (should show venv path)
where python
```
</details>

### 2. Install the Connector

```bash
# Install the connector (venv should be active from step 1)
pip install -e .
```

### 3. Set Up Credentials

**Copy and edit the environment file:**

<details>
<summary><b>🐧 Linux/macOS</b></summary>

```bash
# Copy the example file
cp config/example.env config/.env

# Edit with your actual credentials
nano config/.env

# Load the environment variables
source config/.env

# Verify variables are set
echo $INORBIT_API_KEY
echo $MIR_USERNAME
echo $MIR_PASSWORD
```
</details>

<details>
<summary><b>🪟 Windows</b></summary>

```cmd
# Copy the example file
copy config\example.env config\.env

# Edit with your actual credentials
notepad config\.env

# Set the environment variables manually (simplest approach)
set INORBIT_API_KEY=your-actual-api-key
set MIR_USERNAME=admin
set MIR_PASSWORD=your-actual-password

# Verify variables are set
echo %INORBIT_API_KEY%
echo %MIR_USERNAME%
echo %MIR_PASSWORD%
```
</details>

**Required credentials:**
- **InOrbit API Key**: Get from [InOrbit Developer Console](https://developer.inorbit.ai/docs#configuring-environment-variables)
- **MiR Username/Password**: Your MiR robot's web interface credentials
- **InOrbit Robot Key**: Set directly in config file (unique per robot)





### 4. Configuration

The connector uses a **single configuration file** with fleet-wide defaults and per-robot overrides. We provide two example configurations:

- **`config/fleet.simple.example.yaml`** - Minimal setup for basic configurations
- **`config/fleet.example.yaml`** - Comprehensive example with advanced features (SSL, cameras, etc.)

<details>
<summary><b>🐧 Linux/macOS Setup</b></summary>

```bash
# For basic setup (recommended for first-time users)
cp config/fleet.simple.example.yaml config/my_fleet.yaml

# OR for advanced setup (SSL, cameras, etc.)
cp config/fleet.example.yaml config/my_fleet.yaml

# Edit the configuration for your robots
nano config/my_fleet.yaml  # or vim, code, etc.
```
</details>

<details>
<summary><b>🪟 Windows Setup</b></summary>

```cmd
# For basic setup (recommended for first-time users)
copy config\fleet.simple.example.yaml config\my_fleet.yaml

# OR for advanced setup (SSL, cameras, etc.)
copy config\fleet.example.yaml config\my_fleet.yaml

# Edit the configuration for your robots
notepad config\my_fleet.yaml
```
</details>

The configuration file uses a simple inheritance model:
- **Common section**: Settings shared by all robots  
- **Robot sections**: Override common settings as needed

Both example files include detailed comments explaining each setting.



### 5. Run the Connector

**Make sure your virtual environment is activated:**

<details>
<summary><b>🐧 Linux/macOS</b></summary>

```bash
# Activate virtual environment
source venv/bin/activate

# Load environment variables
source config/.env

# Run connector
inorbit_mir_connector -c config/my_fleet.yaml -id restocker-rs-1
```
</details>

<details>
<summary><b>🪟 Windows</b></summary>

```cmd
# Activate virtual environment
venv\Scripts\activate

# Set environment variables (same as step 3)
set INORBIT_API_KEY=your-actual-api-key
set MIR_USERNAME=admin
set MIR_PASSWORD=your-actual-password

# Run connector
inorbit_mir_connector -c config/my_fleet.yaml -id restocker-rs-1
```
</details>

**Important**: Run **one connector instance per robot**. Replace `restocker-rs-1` with your actual robot ID from the configuration file.

## 💡 Virtual Environment Tips

<details>
<summary><b>🔧 Managing Your Virtual Environment</b></summary>

**Activating the environment:**
- **Linux/macOS**: `source venv/bin/activate`
- **Windows**: `venv\Scripts\activate`

**Deactivating the environment:**
```bash
deactivate  # Works on all platforms
```

**Check if environment is active:**
- Your prompt should show `(venv)` at the beginning
- **Linux/macOS**: `which python` should show path with `/venv/`
- **Windows**: `where python` should show path with `\venv\`

**Installing additional packages:**
```bash
# Always activate first, then install
pip install package-name
```

**Troubleshooting:**
- If `inorbit_mir_connector` command not found → activate venv first
- If import errors → check venv is active and package installed
- If permission errors on Windows → run terminal as Administrator
- If SQLite errors → use system Python: `/usr/bin/python3 -m venv venv_sqlite`
</details>

## 📁 Configuration Files

The connector includes configuration templates:

- **`config/example.env`** - Environment variables template for credentials
- **`config/fleet.simple.example.yaml`** - Minimal configuration for basic HTTP setups
- **`config/fleet.example.yaml`** - Advanced configuration with SSL, cameras, and all features

Choose the example that best matches your setup:
- **Simple**: Basic HTTP connection, no SSL, minimal features
- **Advanced**: HTTPS/SSL, cameras, custom certificates, full feature set

## 🔧 Configuration Guidelines

1. **Credentials First**: Copy and edit `config/example.env` with your credentials
2. **Start Simple**: Copy `fleet.simple.yaml` for basic setups  
3. **Use Inheritance**: Define common settings once, override per robot
4. **Load Environment**: Always `source config/.env` before running
5. **File Paths**: Use `./` relative paths for cross-platform compatibility

## 🗄️ Database Configuration

The MiR connector uses a database to store mission execution state, enabling features like mission persistence and resumption after connector restarts.

### Database Options

**🧪 Development/Testing:**
```yaml
# In your fleet configuration
mission_database_file: "dummy"  # No persistence, in-memory only
```

**🚀 Production (Recommended):**
```yaml
# Each robot should have its own database file
mission_database_file: "/var/lib/mir_connector/missions_robot-id.db"  # SQLite persistence
```

### Default Behavior

If not specified, the connector automatically creates:
- **Database file**: `missions_{robot_id}.db` in the connector directory
- **Format**: SQLite 3.x with ACID compliance
- **Tables**: Automatically created for mission state tracking

### Per-Robot Isolation

**✅ Each robot instance should have its own database:**
```yaml
# Robot 1
robot-1:
  mission_database_file: "/var/lib/mir_connector/missions_robot-1.db"

# Robot 2  
robot-2:
  mission_database_file: "/var/lib/mir_connector/missions_robot-2.db"
```

### Requirements

- **SQLite Support**: Ensure your Python environment includes SQLite3
- **File Permissions**: Database directory must be writable
- **Disk Space**: SQLite files grow with mission history

**Note**: The connector automatically handles database schema creation and migrations.

## 🚀 Running Multiple Robots

For production or multi-robot setups, run one connector instance per robot:

**Linux/macOS:**
```bash
# Terminal 1 - Robot 1
source venv/bin/activate && source config/.env
inorbit_mir_connector -c config/my_fleet.yaml -id robot-1

# Terminal 2 - Robot 2  
source venv/bin/activate && source config/.env
inorbit_mir_connector -c config/my_fleet.yaml -id robot-2

# Or run in background
nohup inorbit_mir_connector -c config/my_fleet.yaml -id robot-1 &
nohup inorbit_mir_connector -c config/my_fleet.yaml -id robot-2 &
```

**Windows:**
```cmd
# Command Prompt 1 - Robot 1
venv\Scripts\activate
set INORBIT_API_KEY=your-key & set MIR_USERNAME=admin & set MIR_PASSWORD=your-password
inorbit_mir_connector -c config/my_fleet.yaml -id robot-1

# Command Prompt 2 - Robot 2
venv\Scripts\activate  
set INORBIT_API_KEY=your-key & set MIR_USERNAME=admin & set MIR_PASSWORD=your-password
inorbit_mir_connector -c config/my_fleet.yaml -id robot-2
```

**Production Notes:**
- Consider using system services (systemd on Linux, Windows Service) for automatic startup
- Docker deployment is also supported for containerized environments
- Each robot maintains its own database file for mission persistence

## Next steps

Now that all of your MiR robots are InOrbit connected, visit the [config as code examples](cac_examples/README.md)
to apply the configuration needed to unlock the full potential of the MiR <> InOrbit Connector. Please note that the features available on your account will depend on your [InOrbit Edition](https://www.inorbit.ai/pricing). Don't hesitate to contact [support@inorbit.ai](support@inorbit.ai) for more information.

## Contributing

Any contribution that you make to this repository will be under the MIT license, as dictated by that [license](https://opensource.org/licenses/MIT).

### Run formatting and lint checks

To make sure that the code is formatted and linted correctly, having installed the `dev` set of requirements run

```bash
black . --line-length=100 --exclude venv
flake8 --max-line-length=100 --exclude venv
```

### Run unit tests

```bash
# Create the virtualenv if not active already
virtualenv venv/
. venv/bin/activate
pip install -e '.[dev]'
pytest -v
```

## Version Bump

Having installed the `dev` set of requirements, to update the version number, commit the changes and create a tag run the following:

```bash
bump-my-version bump minor # Options: major, minor, patch
```

To prevent changes from being applied, use

```bash
bump-my-version bump minor --dry-run --verbose
```

### Build and publish the package

New releases are built and published to PyPi and the Docker repository automatically by GitHub Actions when a new version bump commit is pushed.

> _Note:_ The message of the last commit must contain "Bump version" for the publish job to run. e.g. "Bump version: 1.0.0 -> 1.0.1"

To manually build and publish the package to https://test.pypi.org/, run:

```bash
pip install .[dev] # Install dependencies
python -m build --sdist # Build the package
twine check dist/* # Run checks
twine upload --repository testpypi dist/* # Upload to test PyPI. $HOME/.pypirc should exist and contain the api tokens. See https://pypi.org/help/#apitoken
```

To manually push the Docker image run `./docker/build.sh --push`

![Powered by InOrbit](../assets/inorbit_github_footer.png)
