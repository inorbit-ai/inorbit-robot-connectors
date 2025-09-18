# SPDX-FileCopyrightText: 2023 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Unit tests for utils module."""

from inorbit_mir_connector.src.utils import (
    to_inorbit_percent,
    parse_number,
    to_gb,
    calculate_usage_percent,
)


class TestToInorbitPercent:
    """Test to_inorbit_percent function."""

    def test_normal_percentage(self):
        """Test normal percentage conversion."""
        assert to_inorbit_percent(50.0) == 0.5
        assert to_inorbit_percent(100.0) == 1.0
        assert to_inorbit_percent(0.0) == 0.0

    def test_out_of_range_values(self):
        """Test values outside 0-100 range are clamped."""
        assert to_inorbit_percent(-10.0) == 0.0
        assert to_inorbit_percent(150.0) == 1.0

    def test_decimal_values(self):
        """Test decimal percentage values."""
        assert to_inorbit_percent(25.5) == 0.255
        assert abs(to_inorbit_percent(99.9) - 0.999) < 0.0001


class TestParseNumber:
    """Test parse_number function."""

    def test_integer_input(self):
        """Test integer input."""
        assert parse_number(42) == 42.0
        assert parse_number(-10) == -10.0

    def test_float_input(self):
        """Test float input."""
        assert parse_number(3.14) == 3.14
        assert parse_number(-2.5) == -2.5

    def test_string_input(self):
        """Test string input with numbers."""
        assert parse_number("42") == 42.0
        assert parse_number("3.14") == 3.14
        assert parse_number("-10.5") == -10.5

    def test_mir_api_formats(self):
        """Test the actual number formats returned by MiR API."""
        # Integer values (from actual MiR API response)
        assert parse_number("100") == 100.0  # Battery percentage
        assert parse_number("51") == 51.0  # CPU load
        assert parse_number("49") == 49.0  # Temperature
        assert parse_number("1024") == 1024.0  # Large integers

        # Decimal values (from actual MiR API response)
        assert parse_number("43.6") == 43.6  # CPU load (30 second)
        assert parse_number("55.74") == 55.74  # Hard drive total size [GB]
        assert parse_number("4.951") == 4.951  # 5V out voltage
        assert parse_number("123.45") == 123.45  # Generic decimal

    def test_string_with_text(self):
        """Test string containing text and numbers."""
        assert parse_number("Temperature: 25.5°C") == 25.5
        assert parse_number("Load: -10.2%") == -10.2

    def test_invalid_input(self):
        """Test invalid input returns None."""
        assert parse_number("no numbers here") is None
        assert parse_number("") is None
        assert parse_number(None) is None

    def test_complex_string(self):
        """Test complex string with multiple numbers."""
        # Should return first number found
        assert parse_number("CPU: 25.5°C, Memory: 80%") == 25.5


class TestToGb:
    """Test to_gb function."""

    def test_gb_unit(self):
        """Test values already in GB."""
        assert to_gb(5.0, "Total size [GB]") == 5.0
        assert to_gb("10.5", "Memory [gb] used") == 10.5

    def test_mb_unit(self):
        """Test MB to GB conversion."""
        assert to_gb(1024, "Size [MB]") == 1.0
        assert to_gb(512, "Memory [mb]") == 0.5

    def test_b_unit(self):
        """Test bytes to GB conversion."""
        gb_in_bytes = 1024 * 1024 * 1024
        assert to_gb(gb_in_bytes, "Size [B]") == 1.0
        assert to_gb(gb_in_bytes * 2, "Memory [b]") == 2.0

    def test_no_unit_assumes_gb(self):
        """Test values without unit indicators assume GB."""
        assert to_gb(3.5, "Total memory") == 3.5

    def test_invalid_value(self):
        """Test invalid values return None."""
        assert to_gb("invalid", "Size [GB]") is None
        assert to_gb(None, "Size [GB]") is None

    def test_case_insensitive(self):
        """Test unit detection is case insensitive."""
        assert to_gb(1024, "Size [MB]") == 1.0
        assert to_gb(1024, "Size [mb]") == 1.0
        assert to_gb(1024, "Size [Mb]") == 1.0


class TestCalculateUsagePercent:
    """Test calculate_usage_percent function."""

    def test_used_and_total(self):
        """Test calculation with used and total values."""
        values = {
            "Total size [GB]": "10.0",
            "Used [GB]": "3.0",
        }
        result = calculate_usage_percent(values, "memory")
        assert result == 30.0

    def test_free_and_total(self):
        """Test calculation with free and total values."""
        values = {
            "Total size [GB]": "10.0",
            "Free [GB]": "7.0",
        }
        result = calculate_usage_percent(values, "memory")
        assert result == 30.0

    def test_mixed_units(self):
        """Test calculation with different units."""
        values = {
            "Total size [GB]": "2.0",
            "Used [MB]": "1024",  # 1 GB
        }
        result = calculate_usage_percent(values, "memory")
        assert result == 50.0

    def test_no_total_size(self):
        """Test when no total size is available."""
        values = {
            "Used [GB]": "3.0",
            "Free [GB]": "7.0",
        }
        result = calculate_usage_percent(values, "memory")
        assert result is None

    def test_zero_total(self):
        """Test when total is zero."""
        values = {
            "Total size [GB]": "0",
            "Used [GB]": "0",
        }
        result = calculate_usage_percent(values, "memory")
        assert result is None

    def test_no_usage_data(self):
        """Test when no usage data is available."""
        values = {
            "Total size [GB]": "10.0",
            "Something else": "value",
        }
        result = calculate_usage_percent(values, "memory")
        assert result is None

    def test_invalid_values(self):
        """Test with invalid numeric values."""
        values = {
            "Total size [GB]": "invalid",
            "Used [GB]": "3.0",
        }
        result = calculate_usage_percent(values, "memory")
        assert result is None

    def test_real_world_diagnostic_data(self):
        """Test with realistic diagnostic data structure."""
        values = {
            "Total size [GB]": "7.64",
            "Used [MB]": "3276.8",  # ~3.2 GB
            "Free [GB]": "4.36",
            "Available [GB]": "4.36",
        }
        result = calculate_usage_percent(values, "memory")
        # Should use used/total calculation: 3276.8MB / 1024 / 7.64GB ≈ 41.88%
        assert abs(result - 41.88) < 0.1  # Allow small floating point differences


class TestIntegration:
    """Integration tests combining multiple utility functions."""

    def test_full_diagnostic_processing_flow(self):
        """Test the full flow of processing diagnostic data."""
        # Simulate diagnostic data as it would come from MiR
        diagnostic_data = {
            "Total size [GB]": "8.0",
            "Used [MB]": "2048",  # 2 GB
            "Free space available [GB]": "6.0",
        }

        # Calculate usage percentage
        usage_pct = calculate_usage_percent(diagnostic_data, "disk")
        assert usage_pct == 25.0  # 2GB / 8GB = 25%

        # Convert to InOrbit format
        inorbit_value = to_inorbit_percent(usage_pct)
        assert inorbit_value == 0.25
