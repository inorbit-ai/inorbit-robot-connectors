import yaml
import os
import logging
from typing import Any, Optional

from pydantic import BaseModel, ValidationError, model_validator

logger = logging.getLogger(__name__)

ROBOT_TYPES = ["MAV", "MAiRA"]


class RobotConfig(BaseModel):
    """Single-robot configuration loaded from robot.yaml."""

    # --- Common ---
    robot_name: str
    robot_type: str                     # MAV or MAiRA
    serial_number: str
    inorbit_api_key: Optional[str] = None
    inorbit_robot_key: Optional[str] = None
    map_yaml_path: Optional[str] = None
    map_frame_id: str = "map"
    log_level: str = "INFO"
    connector_version: str = "0.1.0"
    poll_interval: float = 2.0  

    # --- MAV backends (pick one) ---
    robot_ip: Optional[str] = None          # nexus_python_api
    client_ip: Optional[str] = None         # nexus_python_api
    rest_api_ip: Optional[str] = None       # REST API
    rest_api_port: int = 9000               # REST API
    mav_config_path: Optional[str] = None   # neurapy_mav

    # --- NRC gRPC coupler (nrc_grpc_client) ---
    nrc_mode: bool = False
    nrc_server_address: Optional[str] = None

    # --- MAiRA ---
    socket_ip: Optional[str] = None

    class Config:
        extra = "allow"

    @model_validator(mode="after")
    def _validate_type_fields(self):
        if self.robot_type not in ROBOT_TYPES:
            raise ValueError(
                f"Unknown robot_type '{self.robot_type}'. Must be one of {ROBOT_TYPES}"
            )
        if self.robot_type == "MAV":
            has_nexus = self.robot_ip and self.client_ip
            has_rest = bool(self.rest_api_ip)
            has_mav = bool(self.mav_config_path)
            if not (has_nexus or has_rest or has_mav):
                raise ValueError(
                    "MAV requires one of: (robot_ip + client_ip), rest_api_ip, or mav_config_path"
                )
        elif self.robot_type == "MAiRA":
            if not self.socket_ip:
                raise ValueError("socket_ip is required for MAiRA")
        if self.nrc_mode and not self.nrc_server_address:
            raise ValueError("nrc_server_address is required when nrc_mode is true")
        return self

    @property
    def backend_type(self) -> str:
        if self.robot_type == "MAiRA":
            return "maira"
        if self.robot_ip and self.client_ip:
            return "nexus_python"
        if self.rest_api_ip:
            return "nexus_rest"
        return "neurapy_mav"

    @property
    def is_mav(self) -> bool:
        return self.robot_type == "MAV"

    @property
    def is_maira(self) -> bool:
        return self.robot_type == "MAiRA"


def _expand_env_vars(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {key: _expand_env_vars(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [_expand_env_vars(item) for item in obj]
    elif isinstance(obj, str):
        return os.path.expandvars(obj)
    return obj


def load_config(config_path: str) -> RobotConfig:
    with open(config_path, "r", encoding="utf-8") as f:
        raw = _expand_env_vars(yaml.safe_load(f) or {})
    return RobotConfig(**raw)


def format_validation_error(error: ValidationError) -> str:
    messages = []
    for err in error.errors():
        path = " -> ".join(str(loc) for loc in err["loc"])
        if path:
            messages.append(f"  - Field '{path}': {err['msg']}")
        else:
            messages.append(f"  - {err['msg']}")
    return "Config validation failed:\n" + "\n".join(messages)
