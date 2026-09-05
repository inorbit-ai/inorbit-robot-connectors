# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest
from inorbit_omron_connector.src.omron.mock_client import MockOmronClient
from inorbit_omron_connector.src.omron.models import JobRequest, JobCancelByRobotName, JobRequestDetail

@pytest.mark.asyncio
async def test_connect():
    client = MockOmronClient()
    assert await client.connect() is True

@pytest.mark.asyncio
async def test_seed_and_get_fleet_state():
    client = MockOmronClient()
    await client.connect()
    client.seed_robot("robot1", status="Busy", sub_status="Driving", battery=0.8)
    
    fleet = await client.get_fleet_state()
    assert len(fleet) == 1
    assert fleet[0].namekey == "robot1"
    assert fleet[0].status == "Busy"
    assert fleet[0].subStatus == "Driving"

@pytest.mark.asyncio
async def test_get_data_store_value():
    client = MockOmronClient()
    await client.connect()
    client.seed_robot("robot1", battery=0.5, x=1.0, y=2.0, theta=3.14)
    
    soc = await client.get_data_store_value("StateOfCharge", "robot1")
    assert soc.value == 0.5
    
    pose_x = await client.get_data_store_value("PoseX", "robot1")
    assert pose_x.value == 1.0

@pytest.mark.asyncio
async def test_create_job():
    client = MockOmronClient()
    await client.connect()
    mock_client = MockOmronClient()
    await mock_client.connect()
    job_request = JobRequest(
        namekey="job1",
        jobId="mission1",
        defaultPriority=True,
        details=[JobRequestDetail(dropoffGoal="Kitchen", priority=10)]
    )
    response = await mock_client.create_job(job_request.model_dump())
    assert response is True

@pytest.mark.asyncio
async def test_stop():
    client = MockOmronClient()
    await client.connect()
    client.seed_robot("robot1")

    cancel = JobCancelByRobotName(
        robot="robot1",
        cancelReason="Stop"
    )
    result = await client.stop(cancel.model_dump())
    assert result["namekey"] == "robot1"
    assert result["status"] == "Aborted"


@pytest.mark.asyncio
async def test_data_store_stamp_holds_while_the_value_is_unchanged():
    client = MockOmronClient()
    await client.connect()
    client.seed_robot("Robot1", x=1000.0)

    first = await client.get_data_store_value("PoseX", "Robot1")
    second = await client.get_data_store_value("PoseX", "Robot1")

    assert first.upd.millis == second.upd.millis


@pytest.mark.asyncio
async def test_data_store_stamp_advances_when_the_value_changes():
    client = MockOmronClient()
    await client.connect()
    client.seed_robot("Robot1", x=1000.0)

    first = await client.get_data_store_value("PoseX", "Robot1")
    client.seed_robot("Robot1", x=2000.0)
    second = await client.get_data_store_value("PoseX", "Robot1")

    assert first.upd.millis != second.upd.millis


@pytest.mark.asyncio
async def test_fleet_state_stamp_holds_while_the_status_is_unchanged():
    client = MockOmronClient()
    await client.connect()
    client.seed_robot("Robot1")

    first = (await client.get_fleet_state())[0]
    second = (await client.get_fleet_state())[0]

    assert first.upd.millis == second.upd.millis
