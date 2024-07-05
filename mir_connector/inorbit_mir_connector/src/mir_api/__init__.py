from .mir_api_base import MirApiBaseClass  # noqa: F401
from .mir_api_v2 import MirApiV2  # noqa: F401
from .mir_api_v2 import MirWebSocketV2  # noqa: F401

# Available API versions
APIS = {
    "v2.0": {"rest": MirApiV2, "ws": MirWebSocketV2},
}
