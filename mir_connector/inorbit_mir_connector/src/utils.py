# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Utility functions for MiR connector data processing."""

import re
from typing import Optional


def to_inorbit_percent(value: float) -> float:
    """Convert percentage (0-100) to InOrbit format (0-1).
    
    Args:
        value: Percentage value between 0-100
        
    Returns:
        Normalized value between 0-1
    """
    return max(0.0, min(100.0, value)) / 100.0


def parse_number(value: object) -> Optional[float]:
    """Parse a numeric value from various input types.
    
    Handles strings with decimal/float-like tokens, integers, floats.
    Supports comma as decimal separator.
    
    Args:
        value: Input value to parse (int, float, str, etc.)
        
    Returns:
        Parsed float value or None if parsing fails
    """
    try:
        if isinstance(value, (int, float)):
            return float(value)
        
        s = str(value)
        # Extract first decimal/float-like token
        m = re.search(r"-?\d+(?:[.,]\d+)?", s)
        if not m:
            return None
        num = m.group(0).replace(",", ".")
        return float(num)
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
        if 'Total size' in k:
            total_gb = to_gb(v, k)
        elif 'Used' in k:
            used_gb = to_gb(v, k)
        elif 'Free' in k:
            free_gb = to_gb(v, k)
    
    # Calculate usage percentage
    usage_pct = None
    if total_gb and total_gb > 0:
        if used_gb is not None:
            usage_pct = (used_gb / total_gb) * 100.0
        elif free_gb is not None:
            usage_pct = ((total_gb - free_gb) / total_gb) * 100.0
    
    return usage_pct
