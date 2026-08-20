# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Consistency checks between the cac examples and the keys the connector publishes."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from gausium_open_platform_connector.src.key_values import build_key_values

CAC_DIR = Path(__file__).parent.parent / "cac"
FIXTURES = Path(__file__).parent / "fixtures"

# Published outside the key-value builder, as an event
EXTRA_KEYS = {"mission_tracking"}

ROBOT_DATA = {
    "displayName": "Robot Alpha",
    "modelFamilyCode": "S",
    "modelTypeCode": "Scrubber 50H",
    "softwareVersion": "5.10.2",
}


def load_documents(name: str) -> list[dict]:
    return [doc for doc in yaml.safe_load_all((CAC_DIR / name).read_text()) if doc]


def published_keys() -> set[str]:
    status_v1 = json.loads((FIXTURES / "status_v1.json").read_text())
    status_v2 = json.loads((FIXTURES / "status_v2.json").read_text())
    status_v2["currentTask"]["workMode"]["name"] = "__洗地"  # Expose the cleaning_mode keys
    key_values = build_key_values(status_v1, status_v2, ROBOT_DATA, True, "2.0.0")
    return set(key_values) | EXTRA_KEYS


def test_all_cac_files_parse() -> None:
    for path in CAC_DIR.glob("*.yaml"):
        documents = [doc for doc in yaml.safe_load_all(path.read_text()) if doc]
        assert documents, f"{path.name} has no documents"
        for document in documents:
            assert {"kind", "apiVersion", "metadata", "spec"} <= set(document), path.name


def test_datasource_keys_are_published() -> None:
    keys = published_keys()
    for document in load_documents("data_sources.yaml") + load_documents("mission_tracking.yaml"):
        key_value = document["spec"].get("source", {}).get("keyValue")
        if document["kind"] == "DataSourceDefinition" and key_value:
            assert key_value["key"] in keys, f"datasource for unpublished key {key_value['key']}"


def test_datasource_ids_are_unique() -> None:
    ids = [
        document["metadata"]["id"]
        for document in load_documents("data_sources.yaml")
        + load_documents("mission_tracking.yaml")
        if document["kind"] == "DataSourceDefinition"
    ]
    assert len(ids) == len(set(ids))


def test_status_definitions_match_datasource_ids() -> None:
    datasource_ids = {
        document["metadata"]["id"]
        for document in load_documents("data_sources.yaml")
        if document["kind"] == "DataSourceDefinition"
    }
    for document in load_documents("status_definition.yaml"):
        assert document["metadata"]["id"] in datasource_ids
