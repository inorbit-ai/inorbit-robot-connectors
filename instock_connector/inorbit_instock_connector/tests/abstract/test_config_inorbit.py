#!/usr/bin/env python
# -*- coding: utf-8 -*-

# MIT License
#
# Copyright (C) 2024 InOrbit, Inc.

# Standard
from enum import Enum

# Third Party
import pytest
from pydantic import BaseModel, ValidationError

# InOrbit
from inorbit_instock_connector.src.abstract.config_inorbit import LogLevels, \
    CameraModel, InorbitConnectorModel


class DummyModel(BaseModel):
    pass


def test_log_levels_enum_values():
    assert LogLevels.DEBUG == "DEBUG"
    assert LogLevels.INFO == "INFO"
    assert LogLevels.WARNING == "WARNING"
    assert LogLevels.ERROR == "ERROR"
    assert LogLevels.CRITICAL == "CRITICAL"


def test_log_levels_enum_members():
    assert LogLevels.DEBUG.value == "DEBUG"
    assert LogLevels.INFO.value == "INFO"
    assert LogLevels.WARNING.value == "WARNING"
    assert LogLevels.ERROR.value == "ERROR"
    assert LogLevels.CRITICAL.value == "CRITICAL"


def test_log_levels_enum_iteration():
    expected_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    actual_levels = [level for level in LogLevels]
    assert actual_levels == expected_levels


def test_log_levels_enum_isinstance():
    for level in LogLevels:
        assert isinstance(level, LogLevels)
        assert isinstance(level, Enum)
        assert isinstance(level, str)


def test_camera_model_check_quality_range():
    camera_model = CameraModel(video_url="http://localhost.com")

    # Test case where quality is in range.
    assert camera_model.check_quality_range(1) == 1
    assert camera_model.check_quality_range(50) == 50
    assert camera_model.check_quality_range(100) == 100

    # Test case where quality is not in range
    with pytest.raises(ValueError):
        camera_model.check_quality_range(101)

    with pytest.raises(ValueError):
        camera_model.check_quality_range(-1)

    # Test case where quality is None.
    assert camera_model.check_quality_range(None) is None


def test_camera_model_check_positive():
    camera_model = CameraModel(video_url="http://localhost.com")

    # Test case where value is positive
    assert camera_model.check_positive(1.0) == 1.0
    assert camera_model.check_positive(5.0) == 5.0

    # Test case where value is zero.
    with pytest.raises(ValueError):
        camera_model.check_positive(0.0)

    # Test case where value is negative.
    with pytest.raises(ValueError):
        camera_model.check_positive(-1.0)

    # Test case where value is None.
    assert camera_model.check_positive(None) is None


def test_camera_model_init():
    cm = CameraModel(video_url="http://localhost/", rate=30, quality=100, scaling=1.0)
    assert str(cm.video_url) == "http://localhost/"
    assert cm.rate == 30
    assert cm.quality == 100
    assert cm.scaling == 1.0


def test_camera_model_rate_default():
    cm = CameraModel(video_url="http://localhost/")
    assert cm.rate is None


def test_camera_model_quality_default():
    cm = CameraModel(video_url="http://localhost/")
    assert cm.quality is None


def test_camera_model_scaling_default():
    cm = CameraModel(video_url="http://localhost/")
    assert cm.scaling is None


def test_camera_model_no_url():
    with pytest.raises(ValidationError):
        _ = CameraModel(rate=30, quality=100, scaling=1.0)


def test_api_token_whitespace():
    with pytest.raises(ValidationError):
        _ = InorbitConnectorModel(
            api_token="test token",
            connector_type="type",
            connector_config=BaseModel,
        )


def test_invalid_connector_config():
    with pytest.raises(ValidationError):
        _ = InorbitConnectorModel(
            api_token="test_token",
            connector_type="type",
            connector_config=BaseModel,
        )


def test_invalid_location_tz():
    with pytest.raises(ValidationError):
        _ = InorbitConnectorModel(
            api_token="test_token",
            connector_type="type",
            connector_config=DummyModel(),
            location_tz="invalid_tz",
        )


def test_zero_connector_update_freq():
    with pytest.raises(ValidationError):
        _ = InorbitConnectorModel(
            api_token="test_token",
            connector_type="type",
            connector_config=DummyModel(),
            connector_update_freq=0,
        )


def test_negative_connector_update_freq():
    with pytest.raises(ValidationError):
        _ = InorbitConnectorModel(
            api_token="test_token",
            connector_type="type",
            connector_config=DummyModel(),
            connector_update_freq=-1
        )


def test_valid_inorbit_connector_model():
    instance = InorbitConnectorModel(
        api_token="test_token", connector_type="type", connector_config=DummyModel(),
    )
    assert instance.api_token == "test_token"
    assert instance.connector_type == "type"
    assert isinstance(instance.connector_config, BaseModel)
