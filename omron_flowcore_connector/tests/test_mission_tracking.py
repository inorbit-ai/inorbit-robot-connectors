# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import pytest
import asyncio
import unittest.mock
from inorbit_omron_connector.src.omron.mock_client import MockOmronClient
from inorbit_omron_connector.src.mission.tracking import OmronMissionTracking

@pytest.mark.asyncio
async def test_mission_tracking_flow():
    client = MockOmronClient()
    await client.connect()
    robot_id = "AMR_TEST"
    client.seed_robot(robot_id, status="Available")
    
    # Create a job to track
    await client.create_job({
        "jobId": "mission-test",
        "namekey": "Job-mission-test",
        "details": [{"pickupGoal": "StationA", "priority": 10}, {"dropoffGoal": "StationB", "priority": 10}]
    })
    
    tracker = OmronMissionTracking(client)
    
    original_sleep = asyncio.sleep
    
    async def fast_sleep(delay, *args, **kwargs):
        await original_sleep(max(0.001, delay / 100.0))

    with unittest.mock.patch('asyncio.sleep', side_effect=fast_sleep):
        tracker.start()
        
        try:
            # Wait for mission start
            await asyncio.sleep(4.0)
            
            payload = tracker.get_mission_tracking(robot_id)
            assert payload is not None
            assert payload["missionId"] == "mission-test"
            assert payload["inProgress"] is True
            assert payload["state"] == "in progress"
            
            # Wait for some progress
            await asyncio.sleep(6.0)
            payload = tracker.get_mission_tracking(robot_id)
            assert payload["completedPercent"] > 0.0
            assert payload["state"] == "in progress"

            # Wait for completion (Mock cycle is ~22s total: 2s pending + 20s execution)
            # We are at T=10s. We need to reach >22s.
            await asyncio.sleep(15.0)
            payload = tracker.get_mission_tracking(robot_id)
            assert payload is not None
            assert payload["inProgress"] is False
            assert payload["state"] == "completed"
            assert payload["completedPercent"] == 1.0
            assert "startTs" in payload
            assert "data" in payload
            assert payload["data"]["status"] == "Completed"
            
        finally:
            await tracker.stop()

@pytest.mark.asyncio
async def test_tracking_lifecycle():
    """Verify that start() invokes tasks and stop() cleans them up."""
    client = MockOmronClient()
    await client.connect()
    client.seed_robot("AMR_LIFECYCLE")
    
    tracker = OmronMissionTracking(client)
    
    tracker.start()
    assert len(tracker._running_tasks) == 3
    
    await asyncio.sleep(0.1)
    
    for task in tracker._running_tasks:
        assert not task.done()
        
    await tracker.stop()
    
    assert len(tracker._running_tasks) == 0
    assert tracker._stop_event.is_set()

@pytest.mark.asyncio
async def test_mission_catchup():
    """Verify that tracker fetches missing job details when a segment for an unknown job arrives."""
    mock_api = unittest.mock.MagicMock(spec=OmronMissionTracking(None).api)
    
    # 1. Job Stream is silent (simulating missed connection or latency)
    async def empty_stream():
        # Sleep forever to keep task alive but yielding nothing
        while True:
            await asyncio.sleep(1)
        yield # Unreachable
    mock_api.get_job_stream.side_effect = empty_stream
    
    # 2. Segment Stream yields an event for an unknown job "Job-Missed"
    async def segment_stream():
        await asyncio.sleep(0.1)
        yield {
            "job": "Job-Missed",
            "robot": "Robot-X",
            "seq": 1,
            "status": "InProgress",
            "subStatus": "Driving"
        }
        while True:
            await asyncio.sleep(1)
    mock_api.get_job_segment_stream.side_effect = segment_stream
    
    # 3. get_job_details_by_namekey returns the missing job info (Must be awaitable)
    mock_api.get_job_details_by_namekey = unittest.mock.AsyncMock()
    mock_api.get_job_details_by_namekey.return_value = {
        "jobId": "Job-Missed",
        "namekey": "Job-Missed",
        "lastAssignedRobot": "Robot-X",
        "status": "InProgress",
        "jobType": "P",
        "priority": "High",
        "queuedTimestamp": {"millis": "1000"},
        "upd": {"millis": "1000"}
    }
    
    # 4. get_job_segment_list returns 5 steps (Must be awaitable)
    mock_api.get_job_segment_list = unittest.mock.AsyncMock()
    mock_api.get_job_segment_list.return_value = [{"goalName": "Goal"} for _ in range(5)]
    
    tracker = OmronMissionTracking(mock_api)
    
    # Run
    tracker.start()
    
    try:
        # Wait for processing
        await asyncio.sleep(0.5)
        
        # Verify
        mock_api.get_job_details_by_namekey.assert_awaited_with("Job-Missed")
        
        payload = tracker.get_mission_tracking("Robot-X")
        assert payload is not None
        assert payload["missionId"] == "Job-Missed"
        assert payload["state"] == "in progress"
        assert payload["data"]["priority"] == "High"
        assert payload["completedPercent"] == 0.2
        
    finally:
        await tracker.stop()

@pytest.mark.asyncio
async def test_reproduce_stuck_pending():
    """Attempt to reproduce the issue where missions get stuck in Pending."""
    client = MockOmronClient()
    await client.connect()
    client.seed_robot("AMR_LIFECYCLE")
    
    client.seed_robot("AMR_LIFECYCLE", status="Available")
    
    await client.create_job({
        "jobId": "mission-stuck",
        "details": [{"pickupGoal": "A", "priority": 10}, {"dropoffGoal": "B", "priority": 10}]
    })
    
    tracker = OmronMissionTracking(client)
    
    original_sleep = asyncio.sleep
    async def fast_sleep(delay, *args, **kwargs):
        await original_sleep(delay / 10.0)
    
    with unittest.mock.patch('asyncio.sleep', side_effect=fast_sleep):
        tracker.start()
        
        try:
            states_seen = []
            percentages_seen = []
            
            for _ in range(50):
                payload = tracker.get_mission_tracking("AMR_LIFECYCLE")
                if payload:
                    states_seen.append(payload["state"])
                    percentages_seen.append(payload["completedPercent"])
                await original_sleep(0.1)
                

            unique_percentages = sorted(list(set(percentages_seen)))
            
            assert "in progress" in states_seen or "Driving" in states_seen, "Mission stuck in Pending/Unknown"
            assert len(unique_percentages) > 1, "Percentage never changed"
            assert 1.0 in unique_percentages, "Mission never completed"
            
        finally:
            await tracker.stop()

@pytest.mark.asyncio
async def test_task_sequence_updates():
    """Verify that the tasks array updates correctly as segments progress."""
    # Mock API
    mock_api = unittest.mock.MagicMock(spec=OmronMissionTracking(None).api)

    # 1. Job Stream: Just one job "Job-seq"
    async def job_stream():
        yield {
            "jobId": "Job-seq", "namekey": "Job-seq", 
            "lastAssignedRobot": "Robot-T", "status": "InProgress", 
            "jobType": "M",
            "queuedTimestamp": {"millis": "1000"}
        }
        while True:
            await asyncio.sleep(1)
    mock_api.get_job_stream.side_effect = job_stream
    
    # 2. Segments List: 3 steps
    mock_api.get_job_segment_list = unittest.mock.AsyncMock()
    mock_api.get_job_segment_list.return_value = [
        {"seq": 1, "goalName": "Task1", "subStatus": "S1"},
        {"seq": 2, "goalName": "Task2", "subStatus": "S2"},
        {"seq": 3, "goalName": "Task3", "subStatus": "S3"}
    ]
    
    # 3. Stream Events: Task 1 Start -> Task 1 Done -> Task 2 Start -> ...
    async def segment_stream():
        # Wait before starting events to allow T0 check
        await asyncio.sleep(0.2)
        events = [
            {"job": "Job-seq", "robot": "Robot-T", "seq": 1, "status": "InProgress", "subStatus": "S1"},
            {"job": "Job-seq", "robot": "Robot-T", "seq": 1, "status": "Completed", "subStatus": "S1Done"},
            {"job": "Job-seq", "robot": "Robot-T", "seq": 2, "status": "InProgress", "subStatus": "S2"},
            {"job": "Job-seq", "robot": "Robot-T", "seq": 2, "status": "Completed", "subStatus": "S2Done"},
            {"job": "Job-seq", "robot": "Robot-T", "seq": 3, "status": "InProgress", "subStatus": "S3"},
        ]
        for e in events:
            yield e
            await asyncio.sleep(0.1) # Give time to process
        while True:
            await asyncio.sleep(1)
            
    mock_api.get_job_segment_stream.side_effect = segment_stream
    
    tracker = OmronMissionTracking(mock_api)
    tracker.start()
    
    try:
        # T0: Initial Job
        await asyncio.sleep(0.05) 
        payload = tracker.get_mission_tracking("Robot-T")
        assert len(payload['tasks']) == 3
        # No events yet (Mock waits 0.2s)
        assert payload['tasks'][0]['inProgress'] is False
        
        # T1: Task 1 InProgress (Event at 0.2s)
        await asyncio.sleep(0.2) # T=0.25
        payload = tracker.get_mission_tracking("Robot-T")
        assert payload['tasks'][0]['inProgress'] is True
        
        # T2: Task 1 Completed (Event at 0.3s)
        await asyncio.sleep(0.1) # T=0.35
        payload = tracker.get_mission_tracking("Robot-T")
        assert payload['tasks'][0]['inProgress'] is False
        assert payload['tasks'][0]['completed'] is True
        
        # T3: Task 2 InProgress (Event at 0.4s)
        await asyncio.sleep(0.1) # T=0.45
        payload = tracker.get_mission_tracking("Robot-T")
        assert payload['tasks'][1]['inProgress'] is True
        
        # T4: Task 2 Completed (Event at 0.5s)
        await asyncio.sleep(0.1) # T=0.55
        payload = tracker.get_mission_tracking("Robot-T")
        assert payload['tasks'][1]['completed'] is True
        
    finally:
        await tracker.stop()
