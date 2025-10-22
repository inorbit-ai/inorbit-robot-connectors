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
- **Mission Control**: Dispatch, pause, cancel missions via [Actions](https://developer.inorbit.ai/docs#configuring-action-definitions)
- **Custom Scripts**: Execute custom shell scripts on the connector via Custom Actions
- **Mission Tracking**: Full [Mission Tracking](https://developer.inorbit.ai/docs#configuring-mission-tracking) support
- **SSL Support**: Secure connections with full certificate validation
- **Multi-Robot Fleet Management**: Simplified configuration for managing multiple robots
- **Docker Support**: Production-ready containerized deployment with Docker Compose

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
- **`config/fleet.example.yaml`** - Comprehensive example with advanced features (SSL, database, etc.)

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
inorbit_mir_connector -c config/my_fleet.yaml -id <your-robot-id>
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
inorbit_mir_connector -c config/my_fleet.yaml -id <your-robot-id>
```
</details>

**Important**: Run **one connector instance per robot**. Replace `<your-robot-id>` with your actual robot ID from the configuration file.

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

## 🚀 Running Multiple Robots (Development)

For development or testing with multiple robots, run one connector instance per robot:

<details>
<summary><b>🐧 Linux/macOS</b></summary>

```bash
# Terminal 1 - Robot 1
source venv/bin/activate && source config/.env
inorbit_mir_connector -c config/my_fleet.yaml -id robot-1

# Terminal 2 - Robot 2  
source venv/bin/activate && source config/.env
inorbit_mir_connector -c config/my_fleet.yaml -id robot-2

# Or run in background for testing
nohup inorbit_mir_connector -c config/my_fleet.yaml -id robot-1 &
nohup inorbit_mir_connector -c config/my_fleet.yaml -id robot-2 &
```

</details>

<details>
<summary><b>🪟 Windows</b></summary>

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

</details>

**For production deployments, see the [Production Deployment](#-production-deployment) section below.**

## 🏭 Production Deployment

For production environments, choose between **Docker** (recommended) or **bare-metal** deployment with process supervision.

### 🐳 Docker Deployment (Recommended)

Docker provides the most robust production deployment with automatic restarts, resource management, and easy scaling.

**Benefits:**
- ✅ **Auto-restart**: Containers restart automatically on failure  
- ✅ **Isolation**: Each connector runs in its own container
- ✅ **Resource Control**: CPU and memory limits prevent resource exhaustion
- ✅ **Easy Scaling**: Add robots by duplicating service definitions
- ✅ **Consistent Environment**: Same runtime across deployments
- ✅ **Built-in Health Monitoring**: Works seamlessly with connector resilience features

### Prerequisites

- **Docker** and **Docker Compose** installed on your server
- **SSL Certificates** configured (see [Advanced Configuration](#️-advanced-configuration) section below)
- **Network Access** between Docker host and MiR robot

### Quick Docker Setup

1. **Prepare Configuration Files:**

```bash
# Copy and edit environment file
cp config/example.env config/.env
nano config/.env  # Add your credentials

# Copy and edit fleet configuration  
cp config/fleet.example.yaml config/my_fleet.yaml
nano config/my_fleet.yaml  # Configure your robots
```

2. **Set up SSL Certificates (if using HTTPS):**

Follow the [SSL Certificate Setup](#-ssl-certificate-setup) in the Advanced Configuration section below to configure certificates.

3. **Deploy with Docker Compose:**

```bash
cd docker/
docker compose up -d
```

4. **Verify Deployment:**

```bash
# Check that all containers are running
docker compose ps

# View logs to confirm successful startup
docker compose logs -f
```

### Adding More Robots

To add additional robots to your Docker deployment:

1. **Update Fleet Configuration:**

```yaml
# In config/my_fleet.yaml, add new robot section
new-robot-id:
  inorbit_robot_key: "your-robot-key-here"
  mir_host_address: "192.168.1.100"
  mission_database_file: /app/data/missions_new-robot-id.db
  # ... other robot-specific settings
```

2. **Add Service to Docker Compose:**

```yaml
# In docker/docker-compose.yaml, duplicate and modify:
new-robot-id:
  <<: *mir-connector
  container_name: mir_connector_new_robot_id
  environment:
    - ROBOT_ID=new-robot-id
    - CONFIG_FILE=/config/fleet.yaml
    - LOG_LEVEL=${LOG_LEVEL:-INFO}
```

3. **Deploy All Robots:**

```bash
# Deploy all robots (including the new one)
docker compose up -d

# Or deploy just the new robot
docker compose up -d new-robot-id
```

### Docker Management Commands

**Monitoring:**
```bash
# View all robot logs
docker compose logs -f

# View specific robot logs  
docker compose logs -f robot-1

# Check container status
docker compose ps

# Monitor resource usage
docker stats
```

**Control:**
```bash
# Restart specific robot
docker compose restart robot-1

# Restart all robots
docker compose restart

# Stop all robots
docker compose down

# Stop and remove volumes (⚠️ deletes databases)
docker compose down -v
```

**Updates:**
```bash
# Update and redeploy
git pull
docker compose build --no-cache
docker compose up -d
```

### Troubleshooting Docker Deployment

**Container won't start:**
- Check logs: `docker compose logs robot-1`
- Verify `.env` file exists with correct credentials
- Ensure SSL certificates are in `certs/` directory
- Test network connectivity to MiR robot

**Performance issues:**
- Monitor resources: `docker stats`
- Check container limits in `docker-compose.yaml`
- Review logs for connection errors

### 🔧 Bare-Metal Deployment (Alternative)

For environments where Docker isn't available, deploy directly on the host system with process supervision.

#### Prerequisites

- **Python 3.8+** with virtual environment support
- **Process Supervisor** (systemd, Windows Service, etc.)
- **Network Access** to MiR robots and InOrbit cloud

#### Setup Process

1. **Install Connector** (follow [Quick Start](#-quick-start) section)
2. **Configure Environment Variables** for production
3. **Set up Process Supervisor** (choose your platform below)
4. **Start Services** with automatic restart

#### Environment Configuration

```bash
# Required credentials
export INORBIT_API_KEY="your-api-key"
export MIR_USERNAME="admin"
export MIR_PASSWORD="your-password"

# Optional resilience settings (defaults shown)
export INORBIT_STATUS_HEARTBEAT_ENABLED=true          # Status heartbeat every 30s
export INORBIT_RESTART_ON_EDGESDK_TIMEOUT=true        # Auto-restart on timeout
export INORBIT_EDGESDK_RESTART_TIMEOUT_SECONDS=60     # Restart after 60s timeout
```

#### Process Supervision Setup

<details>
<summary><b>🐧 Linux - systemd (Recommended)</b></summary>

1. **Create service file:**
```bash
sudo nano /etc/systemd/system/mir-connector@.service
```

2. **Add service configuration:**
```ini
[Unit]
Description=MiR InOrbit Connector for %i
After=network.target

[Service]
Type=simple
User=mir-connector
WorkingDirectory=/opt/mir_connector
Environment=INORBIT_API_KEY=your-api-key-here
Environment=MIR_USERNAME=admin
Environment=MIR_PASSWORD=your-password-here
ExecStart=/opt/mir_connector/venv/bin/inorbit_mir_connector -c config/my_fleet.yaml -id %i
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

3. **Enable and start:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable mir-connector@robot-1.service
sudo systemctl start mir-connector@robot-1.service
```

</details>

<details>
<summary><b>🪟 Windows - NSSM Service</b></summary>

1. **Download NSSM** from https://nssm.cc/download
2. **Install service:**
```cmd
nssm install MiRConnector-robot-1
```
3. **Configure in GUI or via command line:**
```cmd
nssm set MiRConnector-robot-1 Application "C:\path\to\venv\Scripts\inorbit_mir_connector.exe"
nssm set MiRConnector-robot-1 AppParameters "-c config/my_fleet.yaml -id robot-1"
nssm set MiRConnector-robot-1 AppDirectory "C:\path\to\mir_connector"
nssm start MiRConnector-robot-1
```

</details>

#### Built-in Resilience Features

The connector automatically handles:
- **Health Monitoring**: Tracks successful communication with InOrbit
- **Auto-restart**: Exits when unhealthy for supervisor to restart
- **Status Heartbeat**: Maintains robot online status every 30 seconds

## ⚙️ Advanced Configuration

This section covers advanced topics for customizing your MiR connector deployment.

### 🗄️ Database Configuration

The connector uses SQLite databases to persist mission data and maintain state across restarts.

**Per-Robot Databases (Recommended):**
```yaml
# config/my_fleet.yaml
robots:
  robot-1:
    database_path: "data/missions_robot-1.db"
  robot-2:
    database_path: "data/missions_robot-2.db"
```

**Default Behavior:**
- If no `database_path` specified: `missions_{robot_id}.db` in working directory
- Database and tables created automatically
- Automatic schema migrations

**Requirements:**
- Database directory must be writable
- Sufficient disk space for mission history

### 🔒 SSL Certificate Setup

For secure HTTPS connections to MiR robots, configure SSL certificates in your deployment.

**Prerequisites:**
- Ensure your MiR robot is configured to use SSL/TLS certificates
- Obtain certificate files from your robot administrator

**Fleet Configuration:**
```yaml
# config/my_fleet.yaml
robots:
  robot-1:
    mir_host_address: "xxx.xxx.x.xxx"
    mir_host_port: 443
    mir_use_ssl: true
    ssl_ca_cert_path: "certs/robot-1/ca.crt"              # Required
    ssl_client_cert_path: "certs/robot-1/client.crt"      # Optional (mutual TLS)
    ssl_client_key_path: "certs/robot-1/client.key"       # Optional (mutual TLS)
    ssl_verify_hostname: false                             # Usually false for IPs
```

**Docker Setup:**
Place certificates in `certs/` directory. Docker Compose automatically mounts `certs/` to `/app/certs/`.

```
certs/robot-1/ca.crt, client.crt, client.key
certs/robot-2/ca.crt, client.crt, client.key
```

**Security:**
- Never commit `.key` files to version control
- Keep certificates updated when robot certificates change


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

After running the command, a commit and tag will be created. To push the changes to the remote repository, run:
```bash
git push --tags
```

### Build and publish the package

New releases are built and published to PyPi and the Docker repository automatically by GitHub Actions when a new version bump commit is pushed.

> _Note:_ The message of the last commit must contain "Bump mir_connector version" for the publish job to run. e.g. "Bump mir_connector version: 1.0.0 -> 1.0.1"

To manually build and publish the package to https://test.pypi.org/, run:

```bash
pip install .[dev] # Install dependencies
python -m build --sdist # Build the package
twine check dist/* # Run checks
twine upload --repository testpypi dist/* # Upload to test PyPI. $HOME/.pypirc should exist and contain the api tokens. See https://pypi.org/help/#apitoken
```

To manually push the Docker image run `./docker/build.sh --push`

![Powered by InOrbit](../assets/inorbit_github_footer.png)
