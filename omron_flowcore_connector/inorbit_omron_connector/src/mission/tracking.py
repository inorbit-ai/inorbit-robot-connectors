# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import asyncio
import logging
import time
from enum import StrEnum
from typing import Dict, Any, Optional, List

from inorbit_omron_connector.src.omron.api_client import OmronApiClient

LOGGER = logging.getLogger(__name__)

class OmronJobStatus(StrEnum):
    """Standardized Omron Job Statuses."""
    QUEUED = "Queued"
    PENDING = "Pending"
    IN_PROGRESS = "InProgress"
    WAITING = "Waiting"
    COMPLETED = "Completed"
    FAILED = "Failed"
    CANCELLED = "Cancelled"
    CANCELED = "Canceled"  # Alternative spelling
    INTERRUPTED = "Interrupted"
    UNKNOWN = "Unknown"


class OmronMissionTracking:
    """Manages MissionTracking for Omron Fleet.
    
    Consumes streaming events from the Omron API (Job Stream and JobSegment Stream)
    and constructs InOrbit Mission Tracking payloads.
    """

    def __init__(self, api_client: OmronApiClient):
        self.api = api_client
        self._stop_event = asyncio.Event()
        self._running_tasks = []
        
        # Cache for active missions per robot
        # Structure: { robot_id: mission_payload }
        self._mission_cache: Dict[str, Dict[str, Any]] = {}

        # Cache for current inorbit mission robot job id
        # Structure: { robot_id: job_id }
        self._current_inorbit_mission_robot_job_id: Dict[str, str] = {}
        
        # Cache for total steps of a job (to calculate progress)
        # Structure: { job_namekey: total_steps }
        self._active_job_totals: Dict[str, int] = {}
        
        # Cache for task list state
        # Structure: { job_namekey: [ {taskId, label, completed, inProgress}, ... ] }
        self._active_job_tasks: Dict[str, List[Dict[str, Any]]] = {}
        
        # Track last update time for cleanup
        # Structure: { job_namekey: timestamp }
        self._job_last_update: Dict[str, float] = {}

        # Cache for simple job status lookup (to support race-condition-free waiting)
        # Structure: { job_namekey: status_string }
        self._job_status_cache: Dict[str, str] = {}
        
        # Max age for cached status before forcing API lookup (seconds)
        self._status_cache_ttl = 5.0


    def start(self):
        """Start background processing tasks."""
        self._running_tasks.append(asyncio.create_task(self._process_job_stream()))
        self._running_tasks.append(asyncio.create_task(self._process_segment_stream()))
        self._running_tasks.append(asyncio.create_task(self._cleanup_loop()))
        LOGGER.info("Started Mission Tracking")

    async def stop(self):
        """Stop background tasks."""
        self._stop_event.set()
        for task in self._running_tasks:
            task.cancel()
        
        try:
            await asyncio.wait_for(
                asyncio.gather(*self._running_tasks, return_exceptions=True),
                timeout=5.0
            )
        except asyncio.TimeoutError:
            LOGGER.warning("Mission tracking tasks failed to stop gracefully within timeout")
            
        self._running_tasks.clear()
        LOGGER.info("Stopped Mission Tracking")

    def set_inorbit_mission_current_robot_job_id(self, robot_id: str, job_id: str):
        self._current_inorbit_mission_robot_job_id[robot_id] = job_id

    def get_mission_tracking(self, robot_id: str) -> Optional[Dict[str, Any]]:
        """Get the current mission payload for a robot."""
        return self._mission_cache.get(robot_id)
        
    async def _process_job_stream(self):
        """Consumes stream of job events."""
        while not self._stop_event.is_set():
            try:
                async for event in self.api.get_job_stream():
                    if self._stop_event.is_set():
                        break
                    
                    robot_id = event.get('lastAssignedRobot')
                    if not robot_id:
                        continue
                    
                    job_key = event.get('namekey')

                    
                    await self._handle_job_update(robot_id, job_key, event)

                # Stream finished expectedly (or empty), wait before retry/reconnect
                await asyncio.sleep(1.0)

            except Exception as e:
                LOGGER.error(f"Error in Job Stream: {e}")
                await asyncio.sleep(5.0)

    async def _handle_job_update(self, robot_id: str, job_key: str, event: Dict[str, Any], update_mission_cache: bool = True):
        """Central logic for updating job state from event data."""
        job_id = event.get('jobId')

        if job_id and job_id == self._current_inorbit_mission_robot_job_id.get(robot_id):
            return

        self._job_last_update[job_key] = time.time()
        
        raw_status = event.get('status')
        status = self._normalize_status(raw_status)
        self._job_status_cache[job_key] = status
        
        job_type = event.get('jobType', 'Unknown')
        
        if job_key not in self._active_job_totals:
            try:
                segments = await self.api.get_job_segment_list(job_key)
                self._active_job_totals[job_key] = len(segments)
                
                self._active_job_tasks[job_key] = [
                    {
                        "taskId": str(s.get("seq", i+1)),
                        "label": s.get("goalName", s.get("subStatus", f"Step {i+1}")),
                        "completed": False,
                        "inProgress": False
                    }
                    for i, s in enumerate(segments)
                ]
            except Exception as e:
                LOGGER.warning(f"Failed to fetch segments for {job_key}: {e}")
                self._active_job_totals[job_key] = 10 # Fallback
                self._active_job_tasks[job_key] = []

                self._active_job_tasks[job_key] = []
        
        is_complete = status in [
            OmronJobStatus.COMPLETED,
            OmronJobStatus.CANCELLED,
            OmronJobStatus.CANCELED,
            OmronJobStatus.FAILED
        ]
        
        inorbit_state = self._map_state(status)
        inorbit_status = self._map_health(status, event.get('failCount', 0))
        
        queued_ts_obj = event.get('queuedTimestamp', {})
        start_ts_str = queued_ts_obj.get('millis', '0') if isinstance(queued_ts_obj, dict) else '0'
        
        try:
             start_ts = int(start_ts_str)
             if start_ts == 0:
                 start_ts = int(time.time() * 1000)
        except (ValueError, TypeError):
             start_ts = int(time.time() * 1000)

        created_ts = start_ts
        
        data = {
            "jobId": event.get('jobId', job_key),
            "namekey": job_key,
            "status": status,
            "jobType": job_type,
            "priority": event.get('priority', 'Normal'),
            "created": created_ts,
            "assigned": start_ts,
            "finished": event.get('finished'),
            "creator": event.get('creator', 'Unknown'),
            "isSuccess": inorbit_status == "ok",
            "isSuccessNum": 1 if inorbit_status == "ok" else 0
        }

        payload = {
            "missionId": event.get('jobId', job_key),
            "inProgress": not is_complete,
            "status": inorbit_status,
            "state": inorbit_state, # "in progress" / "completed"
            "label": self._map_label(job_type),
            "completedPercent": 1.0 if is_complete else 0.0,
            "startTs": start_ts,
            "data": data,
            "tasks": self._active_job_tasks.get(job_key, [])
        }

        if update_mission_cache:
            self._mission_cache[robot_id] = payload
        
    async def _process_segment_stream(self):
        """Consumes stream of job segment events."""
        while not self._stop_event.is_set():
            try:
                async for event in self.api.get_job_segment_stream():
                    if self._stop_event.is_set():
                        break
                    
                    robot_id = event.get('robot')
                    if not robot_id:
                        continue
                    
                    job_key = event.get('job')
                    
                    if job_key not in self._active_job_totals:
                        try:
                             job_data = await self.api.get_job_details_by_namekey(job_key)
                             if job_data:
                                  await self._handle_job_update(robot_id, job_key, job_data)
                        except Exception as e:
                             LOGGER.warning(f"Failed to catch-up missing job {job_key}: {e}")
                    
                    if job_key not in self._active_job_totals:
                        continue
                        
                    self._job_last_update[job_key] = time.time()
                    
                    seq = event.get('seq', 0)
                    total = self._active_job_totals.get(job_key, 10)
                    percent = min(seq / total, 0.99)
                    
                    seg_status = event.get('status', '') # InProgress / Completed
                    
                    if job_key in self._active_job_tasks:
                        for task in self._active_job_tasks[job_key]:
                            if task['taskId'] == str(seq):
                                if seg_status == 'InProgress':
                                    task['inProgress'] = True
                                    task['completed'] = False
                                elif seg_status == 'Completed':
                                    task['inProgress'] = False
                                    task['completed'] = True
                    
                    if robot_id in self._mission_cache:
                        mission = self._mission_cache[robot_id]
                        
                        if job_key in [mission['missionId'], mission.get('data', {}).get('namekey')]:
                            mission['completedPercent'] = percent
                            if 'data' in mission:
                                 mission['data']['subStatus'] = event.get('subStatus')

                # Stream finished expectedly (or empty), wait before retry/reconnect
                await asyncio.sleep(1.0)

            except Exception as e:
                LOGGER.error(f"Error in Segment Stream: {e}")
                await asyncio.sleep(5.0)

    async def _cleanup_loop(self):
        """Periodically cleans up stale jobs."""
        while not self._stop_event.is_set():
            await asyncio.sleep(60)
            now = time.time()
            api_timeout = 300 # 5 minutes expiry
            
            expired_jobs = [k for k, v in self._job_last_update.items() if now - v > api_timeout]
            for job in expired_jobs:
                self._active_job_totals.pop(job, None)
                self._active_job_tasks.pop(job, None)
                self._job_status_cache.pop(job, None)
                self._job_last_update.pop(job, None)

    def _map_state(self, status: str) -> str:
        # Map normalized status to InOrbit state
        if status in [OmronJobStatus.PENDING, OmronJobStatus.IN_PROGRESS]:
            return "in progress"
        if status == OmronJobStatus.COMPLETED:
            return "completed"
        if status in [OmronJobStatus.CANCELLED, OmronJobStatus.CANCELED]:
            return "aborted"
        if status == OmronJobStatus.FAILED:
            return "failed"
        return "unknown"


    async def get_job_state(self, job_id: str, job_key: str) -> Optional[str]:
        """Get the last known state for a specific job key (namekey).
        
        Checks internal cache first. If missing OR stale, queries API and updates cache.
        
        Returns:
            Status string (from OmronJobStatus) or None if unknown.
        """
        now = time.time()
        cached_status = self._job_status_cache.get(job_key)
        last_update = self._job_last_update.get(job_key, 0)
        
        # 1. Check Cache Validity
        is_stale = (now - last_update) > self._status_cache_ttl
        
        if cached_status and not is_stale:
            return cached_status
            
        # 2. API Fallback (on miss or stale)
        try:
            job_details = await self.api.get_job_details_by_job_id(job_id)
            if job_details:
                raw_status = job_details.get("status")
                # Normalize status
                status = self._normalize_status(raw_status)
                
                robot_id = job_details.get("lastAssignedRobot")
                
                # If we have robot_id, we can perform a full update which populates all caches
                if robot_id:
                    # Don't update the mission cache here, as this might be an old job
                    # and we don't want to overwrite the robot's current status.
                    await self._handle_job_update(robot_id, job_key, job_details, update_mission_cache=False)
                elif status:
                     # Otherwise just update the status cache
                     self._job_status_cache[job_key] = status
                     self._job_last_update[job_key] = time.time()
                
                return status
                
        except Exception as e:
            LOGGER.debug(f"Failed to fetch details for job {job_id}: {e}")
            # If API fails but we have stale cache, return it as backup
            if cached_status:
                LOGGER.warning(f"Returning stale status for job {job_id} due to API failure")
                return cached_status
            
        return None


    def _map_health(self, status: str, fail_count: int) -> str:
        if status == OmronJobStatus.FAILED or fail_count > 0:
            return "error"
        if status == OmronJobStatus.INTERRUPTED or 'Interrupted' in status:
            return "warning"
        return "ok"


    def _map_label(self, job_type: str) -> str:
        mapping = {
            'P': 'Pickup',
            'D': 'Dropoff',
            'PD': 'Delivery',
            'M': 'Multi-Goal'
        }
        return mapping.get(job_type, job_type)

    def _normalize_status(self, raw_status: Optional[str]) -> str:
        """normalize raw status string to Enum."""
        if not raw_status:
            return OmronJobStatus.UNKNOWN
        
        try:
            return OmronJobStatus(raw_status)
        except ValueError:
            pass
        
        for member in OmronJobStatus:
            if member.value.lower() == raw_status.lower():
                return member
        
        return raw_status
