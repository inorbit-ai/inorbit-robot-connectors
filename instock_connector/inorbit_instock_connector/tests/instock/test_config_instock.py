#!/usr/bin/env python
# -*- coding: utf-8 -*-

# MIT License
#
# Copyright (C) 2024 InOrbit, Inc.

import pytest

from inorbit_instock_connector.src.instock.config_instock import (
    InstockConfigModel,
    DEFAULT_INSTOCK_API_VERSION,
)


def test_instock_config_model_init():
    valid_api_url = "https://example.com/"
    valid_api_token = "123a"
    valid_org_id = "123abc"
    valid_site_id = "abc123"
    valid_pose = {"x": 0.0, "y": 0.0, "yaw": 0.0}

    model = InstockConfigModel(
        instock_api_url=valid_api_url,
        instock_api_token=valid_api_token,
        instock_api_version=DEFAULT_INSTOCK_API_VERSION,
        instock_site_id=valid_site_id,
        instock_org_id=valid_org_id,
        pose=valid_pose,
    )
    assert str(model.instock_api_url) == valid_api_url
    assert model.instock_api_token == valid_api_token
    assert model.instock_api_version == DEFAULT_INSTOCK_API_VERSION
    assert model.instock_site_id == valid_site_id
    assert model.pose == valid_pose


def test_instock_config_model_pose_validation():
    valid_pose = {"x": 0.0, "y": 0.0, "yaw": 0.0}
    invalid_pose_keys = {"a": 0.0, "b": 0.0, "c": 0.0}
    invalid_pose_type = {"x": 1, "y": 2, "yaw": "non_numeric"}

    model = InstockConfigModel(
        instock_api_url="https://example.com/",
        instock_api_token="123a",
        instock_api_version=DEFAULT_INSTOCK_API_VERSION,
        instock_site_id="abc123",
        instock_org_id="123abc",
        pose=valid_pose,
    )

    with pytest.raises(ValueError):
        model.pose_validation(invalid_pose_keys)

    with pytest.raises(ValueError):
        model.pose_validation(invalid_pose_type)


def test_instock_config_model_api_version_validation():
    valid_api_version = DEFAULT_INSTOCK_API_VERSION
    invalid_api_version = "2.0.0"

    model = InstockConfigModel(
        instock_api_url="https://example.com/",
        instock_api_token="123a",
        instock_api_version=valid_api_version,
        instock_site_id="abc123",
        instock_org_id="123abc",
        pose={"x": 0.0, "y": 0.0, "yaw": 0.0},
    )

    with pytest.raises(ValueError):
        model.api_version_validation(invalid_api_version)
