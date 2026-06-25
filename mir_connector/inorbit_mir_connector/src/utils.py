# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Utility functions for MiR connector data processing."""

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


def to_inorbit_percent(value: float, label: str = "") -> float:
    """Scale a 0-100 percentage to InOrbit's 0-1 fraction.

    Does NOT clamp. An out-of-range input is logged at WARNING and passed
    through (scaled), so a bad value surfaces in the UI instead of being
    silently masked. A previous silent clamp hid a unit bug where an absolute
    battery capacity (mAh) was matched as the percentage and pinned to 100%.

    Args:
        value: Percentage value, normally between 0-100
        label: Optional name of the metric being converted, included in the
            out-of-range warning so it is traceable to its source.

    Returns:
        The value scaled by 1/100 (not clamped)
    """
    if not 0.0 <= value <= 100.0:
        target = f" for '{label}'" if label else ""
        logger.warning(
            "Percentage value %s%s is outside the expected 0-100 range; "
            "publishing scaled value anyway",
            value,
            target,
        )
    return value / 100.0


def parse_number(value: object) -> Optional[float]:
    """Parse a numeric value from various input types.

    Handles strings with decimal/float-like tokens, integers, floats.
    Based on actual MiR API format: simple integers and decimals with periods only.

    Examples:
        "123.45" -> 123.45 (MiR API decimal format)
        "1024" -> 1024.0 (MiR API integer format)

    Args:
        value: Input value to parse (int, float, str, etc.)

    Returns:
        Parsed float value or None if parsing fails
    """
    try:
        if isinstance(value, (int, float)):
            return float(value)

        s = str(value).strip()
        if not s:
            return None

        # Extract standard number format (what MiR API actually returns)
        m = re.search(r"-?\d+(?:\.\d+)?", s)
        if not m:
            return None

        return float(m.group(0))
    except (ValueError, AttributeError):
        # Expected parsing errors for malformed numbers
        return None


def to_gb(val: object, key: str) -> Optional[float]:
    """Convert a value to gigabytes based on unit indicators in the key.

    Args:
        val: Value to convert
        key: Key string containing unit indicators like [GB], [MB], [B]

    Returns:
        Value converted to GB or None if parsing fails
    """
    n = parse_number(val)
    if n is None:
        return None
    k = key.lower()
    if "[gb]" in k:
        return n
    if "[mb]" in k:
        return n / 1024.0
    if "[b]" in k:
        return n / (1024.0 * 1024.0 * 1024.0)
    # Assume already in GB if unit not specified
    return n


def calculate_usage_percent(diagnostic_values: dict, key_name: str) -> Optional[float]:
    """Calculate usage percentage from diagnostic values.

    Looks for total, used, and free values in the diagnostic data
    and calculates usage percentage.

    Args:
        diagnostic_values: Dictionary of diagnostic values
        key_name: Base key name for identifying relevant values

    Returns:
        Usage percentage (0-100) or None if calculation fails
    """
    total_gb = used_gb = free_gb = None

    for k, v in diagnostic_values.items():
        if "Total size" in k:
            total_gb = to_gb(v, k)
        elif "Used" in k:
            used_gb = to_gb(v, k)
        elif "Free" in k:
            free_gb = to_gb(v, k)

    # Calculate usage percentage
    usage_pct = None
    if total_gb and total_gb > 0:
        if used_gb is not None:
            usage_pct = (used_gb / total_gb) * 100.0
        elif free_gb is not None:
            usage_pct = ((total_gb - free_gb) / total_gb) * 100.0

    return usage_pct
