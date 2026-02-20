# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

from typing import List, Dict, Any, AsyncIterator, Optional
import time
import asyncio
import logging

from inorbit_omron_connector.src.omron.models import (
    RobotResponse, OmronUpdate, DataStoreResponse
)

LOGGER = logging.getLogger(__name__)

class MockOmronResponse:
    def __init__(self, json_data: List[Dict[str, Any]]):
        self._json = json_data

    def json(self):
        return self._json

class MockOmronClient:
    def __init__(self):
        self._robots: Dict[str, Dict[str, Any]] = {}
        self._connected = False
        self._current_job_id: Dict[str, str] = {} # robot_id -> job_id
        self._jobs_db: Dict[str, Dict[str, Any]] = {} # job_id -> job_details

    async def connect(self):
        self._connected = True
        return True

    def seed_robot(self, robot_id: str, status: str = "Available", sub_status: str = "Unallocated", 
                   battery: float = 1.0, x: float = 0.0, y: float = 0.0, theta: float = 0.0,
                   ip_address: str = "127.0.0.1"):
        """Seeds a robot with initial state."""
        self._robots[robot_id] = {
            "status": status,
            "subStatus": sub_status,
            "battery": battery,
            "pose": {"x": x, "y": y, "theta": theta},
            "ipAddress": ip_address,
            "jobs": []
        }

    async def get_fleet_state(self) -> List[RobotResponse]:
        if not self._connected:
            raise ConnectionError("Not connected")
        
        response = []
        now_millis = int(time.time() * 1000)
        for robot_id, data in self._robots.items():
            response.append(RobotResponse(
                namekey=robot_id,
                upd=OmronUpdate(millis=now_millis),
                status=data["status"],
                subStatus=data["subStatus"],
                ipAddress=data.get("ipAddress")
            ))
        return response

    async def get_data_store_value(self, key: str, robot_id: str) -> DataStoreResponse | List[DataStoreResponse]:
        if not self._connected:
            raise ConnectionError("Not connected")
        
        # Simplified mapping for mock
        mapped = {
            "StateOfCharge": "battery", # Maps to robot["battery"]
            "PoseX": "pose.x", # Maps to robot["pose"]["x"]
            "PoseY": "pose.y", # Maps to robot["pose"]["y"]
            "PoseTh": "pose.theta", # Maps to robot["pose"]["theta"]
            "RobotIP": "ipAddress" # Maps to robot["ipAddress"]
        }
        
        attr_path = mapped.get(key)
        if not attr_path:
            # If the key is not in our mapped list, we can't provide a value
            return []

        now_millis = int(time.time() * 1000)

        def _get_value_from_robot(robot_data: Dict[str, Any], path: str):
            parts = path.split('.')
            current_val = robot_data
            for part in parts:
                if isinstance(current_val, dict) and part in current_val:
                    current_val = current_val[part]
                else:
                    return None # Path not found
            return current_val

        if robot_id == "*":
            res = []
            for rid, data in self._robots.items():
                val = _get_value_from_robot(data, attr_path)
                if val is not None:
                    res.append(DataStoreResponse(
                        namekey=f"{key}:{rid}",
                        upd=OmronUpdate(millis=now_millis),
                        value=val
                    ))
            return res
        
        # Specific robot
        data = self._robots.get(robot_id)
        if not data:
            raise ValueError(f"Robot {robot_id} not found")
        
        val = _get_value_from_robot(data, attr_path)
        if val is None:
            return DataStoreResponse(
                namekey=f"{key}:{robot_id}",
                upd=OmronUpdate(millis=now_millis),
                value=0 # Default value
            )
            
        return DataStoreResponse(
            namekey=f"{key}:{robot_id}",
            upd=OmronUpdate(millis=now_millis),
            value=val
        )

    async def create_job(self, job_request: Dict[str, Any]) -> bool:
        """Accept dict or JobRequest model."""
        if not self._connected:
            raise ConnectionError("Not connected")
        LOGGER.info(f"MOCK: Creating job: {job_request}")
        
        job_id = job_request.get("jobId")
        namekey = job_request.get("namekey") or f"Job-{job_id}"
        now_ms = int(time.time() * 1000)
        
        self._jobs_db[namekey] = {
            "jobId": job_id,
            "namekey": namekey,
            "status": "Pending",
            "jobType": "M",
            "priority": "Normal",
            "queuedTimestamp": {"millis": str(now_ms)},
            "upd": {"millis": str(now_ms)},
            # Try to infer robot if possible, or leave empty
            "lastAssignedRobot": None,
            "details": job_request.get("details") # Store details for segment simulation
        }
        
        return True

    async def create_dropoff(self, dropoff_request: Dict[str, Any]) -> bool:
        """Simulate creating a Dropoff job."""
        if not self._connected:
            raise ConnectionError("Not connected")
        
        LOGGER.info(f"MOCK: Creating dropoff job: {dropoff_request}")
        
        # Extract fields
        job_id = dropoff_request.get("jobId")
        goal = dropoff_request.get("goal")
        robot = dropoff_request.get("robot")
        priority = dropoff_request.get("priority", 1)
        
        namekey = dropoff_request.get("namekey") or f"Job-{job_id}"
        now_ms = int(time.time() * 1000)
        
        self._jobs_db[namekey] = {
            "jobId": job_id,
            "namekey": namekey,
            "status": "Pending",
            "jobType": "D",
            "priority": str(priority),
            "queuedTimestamp": {"millis": str(now_ms)},
            "upd": {"millis": str(now_ms)},
            "lastAssignedRobot": robot, # Dropoff is assigned to a specific robot
            "goal": goal,
            "details": None # Dropoff doesn't have details
        }
        
        # If we have a robot, queue it up for execution (simplified)
        if robot and robot in self._robots:
             self._current_job_id[robot] = namekey

        return True

    async def stop(self, job_cancel: Dict[str, Any]) -> Dict[str, Any]:
        """Accept dict and handle cancel by robot or job namekey."""
        if not self._connected:
            raise ConnectionError("Not connected")
        
        LOGGER.info(f"MOCK: Stopping robot with JobCancel: {job_cancel}")
        
        robot_id = job_cancel.get("robot")
        job_namekey = job_cancel.get("jobNamekey")
        
        if robot_id and robot_id in self._robots:
            # Mark current job as aborted if exists
            current_job = self._current_job_id.get(robot_id)
            if current_job and current_job in self._jobs_db:
                self._jobs_db[current_job]["status"] = "Aborted"
            
            self._robots[robot_id]["jobs"] = []
            self._robots[robot_id]["subStatus"] = "Unallocated"
            return {"namekey": robot_id, "status": "Aborted", "message": "Robot stopped"}
        
        if job_namekey and job_namekey in self._jobs_db:
            self._jobs_db[job_namekey]["status"] = "Aborted"
            # If it was assigned to a robot, free the robot
            assigned_robot = self._jobs_db[job_namekey].get("lastAssignedRobot")
            if assigned_robot and assigned_robot in self._robots:
                self._robots[assigned_robot]["subStatus"] = "Unallocated"
                if self._current_job_id.get(assigned_robot) == job_namekey:
                    del self._current_job_id[assigned_robot]
            
            return {"namekey": job_namekey, "status": "Aborted", "message": "Job canceled"}

        return {"error": "Invalid cancel request"}

    async def get_job_stream(self) -> AsyncIterator[Dict[str, Any]]:
        """Streams events from /Job/Stream.
        Monitors _jobs_db for job status changes and streams them.
        """
        if not self._robots:
            LOGGER.warning("No robots seeded for mock mission stream")
            return
        
        target_robot = list(self._robots.keys())[0]
        LOGGER.info(f"MOCK: Starting job stream monitor for {target_robot}")
        
        last_processed_status: Dict[str, str] = {} # job_id -> status

        while True:
            # Check all jobs in DB
            active_jobs = list(self._jobs_db.values())
            
            for job in active_jobs:
                job_key = job["namekey"]
                current_status = job["status"]
                
                # If this is a new job or status changed, yield event
                if job_key not in last_processed_status or last_processed_status[job_key] != current_status:
                    now_ms = int(time.time() * 1000)
                    job["upd"] = {"millis": str(now_ms)}
                    
                    # Update robot status based on job
                    if current_status == "InProgress":
                        self._robots[target_robot]["status"] = "InProgress"
                        # Simulate progression to Completed after some time if not simulating segments
                        # But here we let the segment loop drive it or just simple timeout
                        
                    elif current_status == "Completed" or current_status == "Aborted":
                         self._robots[target_robot]["status"] = "Available"
                         self._robots[target_robot]["subStatus"] = "Unallocated"

                    yield job
                    last_processed_status[job_key] = current_status
            
            # Dispatch logic: Assign pending jobs to available robots
            for job_key, job in self._jobs_db.items():
                if job["status"] == "Pending":
                    # If job has no assigned robot, try to find one
                    if not job["lastAssignedRobot"]:
                        # Find a robot that is Available
                        candidate = None
                        for r_id, r_data in self._robots.items():
                            if r_data["status"] == "Available":
                                candidate = r_id
                                break
                        
                        if candidate:
                             job["lastAssignedRobot"] = candidate
                             self._current_job_id[candidate] = job_key
                             LOGGER.info(f"MOCK: Dispatched job {job_key} to {candidate}")

                    # If robot is assigned, move to InProgress
                    if job["lastAssignedRobot"]:
                        await asyncio.sleep(2.0) # Simulate startup time
                        job["status"] = "InProgress"
                        job["upd"] = {"millis": str(int(time.time() * 1000))}

                elif job["status"] == "InProgress":
                    # Auto-complete safety net
                    pass

            await asyncio.sleep(1.0)

    def _generate_segments_for_job(self, job: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Helper to generate segments dynamically based on job details."""
        job_key = job["namekey"]
        segments_to_run = []
        
        # Dynamic segment generation
        if job["jobType"] == "D":
            # Single segment for dropoff
            segments_to_run.append({
                "seq": 1, 
                "segmentId": f"{job_key}-1", 
                "goalName": job.get("goal", "Unknown"), 
                "segmentType": "Dropoff", 
                "subStatus": "Driving" # Simplified
            })
        elif job["jobType"] == "M":
            # Multi-goal job
            details = job.get("details")
            if details:
                for i, detail in enumerate(details):
                    # detail might be a dict or object depending on how it was stored
                    # The create_job stores the dict form from job_request.get("details")
                    d_obj = detail if isinstance(detail, dict) else detail.model_dump()
                    
                    goal_name = d_obj.get("dropoffGoal") or d_obj.get("pickupGoal") or d_obj.get("goal") or "Unknown"
                    seg_type = "Dropoff" if d_obj.get("dropoffGoal") else "Pickup"
                    
                    segments_to_run.append({
                        "seq": i + 1,
                        "segmentId": f"{job_key}-{i+1}",
                        "goalName": goal_name,
                        "segmentType": seg_type,
                        "subStatus": "Driving"
                    })
        
        if not segments_to_run:
            # Fallback if no details
            segments_to_run = [
                {"seq": 1, "segmentId": f"{job_key}-1", "goalName": "Pickup", "segmentType": "Pickup", "subStatus": "Driving"},
                {"seq": 2, "segmentId": f"{job_key}-2", "goalName": "Dropoff", "segmentType": "Dropoff", "subStatus": "Docking"}
            ]
        return segments_to_run

    async def get_job_segment_stream(self) -> AsyncIterator[Dict[str, Any]]:
        """Streams events from /JobSegment/Stream.
        Simulates segments for InProgress jobs.
        """
        target_robot = list(self._robots.keys())[0]
        
        # Track progress of segments per job
        # job_key -> current_segment_index
        job_progress: Dict[str, int] = {}
        
        while True:
            active_jobs = [j for j in self._jobs_db.values() if j["status"] == "InProgress"]
            
            for job in active_jobs:
                job_key = job["namekey"]
                
                # Init progress
                if job_key not in job_progress:
                    job_progress[job_key] = 0
                
                segments_to_run = self._generate_segments_for_job(job)
                
                current_idx = job_progress[job_key]
                
                if current_idx < len(segments_to_run):
                    seg = segments_to_run[current_idx]
                    
                    # 1. InProgress event
                    yield {
                        "job": job_key, "robot": target_robot, "segmentId": seg["segmentId"],
                        "seq": seg["seq"], "status": "InProgress", "subStatus": seg["subStatus"],
                        "goalName": seg["goalName"], "segmentType": seg["segmentType"], "priority": 1
                    }
                    self._robots[target_robot]["subStatus"] = seg["subStatus"]
                    
                    await asyncio.sleep(5.0) # processing time
                    
                    # 2. Completed event
                    yield {
                            "job": job_key, "robot": target_robot, "segmentId": seg["segmentId"],
                        "seq": seg["seq"], "status": "Completed", "subStatus": "None",
                        "goalName": seg["goalName"], "segmentType": seg["segmentType"], "priority": 1
                    }
                    
                    job_progress[job_key] += 1
                else:
                    # All segments done, mark job specific completed
                    # The job stream loop will pick this up on next iteration
                    job["status"] = "Completed"
                    del job_progress[job_key]
            
            await asyncio.sleep(1.0)

    async def get_job_segment_list(self, job_namekey: str) -> List[Dict[str, Any]]:
        """Returns mock segment list for total steps calculation."""
        # 1. Try to find the job in our DB
        job = self._jobs_db.get(job_namekey)
        
        if job:
            return self._generate_segments_for_job(job)
            
        # 2. Fallback to default if job not found (similar to fallback in generator)
        return [
            {"seq": 1, "segmentId": f"{job_namekey}-1", "goalName": "Pickup", "segmentType": "Pickup", "subStatus": "Driving"},
            {"seq": 2, "segmentId": f"{job_namekey}-2", "goalName": "Dropoff", "segmentType": "Dropoff", "subStatus": "BeforeDropoff"},
            {"seq": 3, "segmentId": f"{job_namekey}-3", "goalName": "Dock", "segmentType": "Dropoff", "subStatus": "Docking"}
        ]

    async def get_job_details_by_namekey(self, job_namekey: str) -> Optional[Dict[str, Any]]:
        """Returns job details for the given key."""
        # 1. Check DB
        if job_namekey in self._jobs_db:
            return self._jobs_db[job_namekey]

        # 2. Check current simulated jobs
        for robot_id, job_id in self._current_job_id.items():
            if job_id == job_namekey:
                now_ms = int(time.time() * 1000)
                return {
                    "jobId": job_namekey,
                    "namekey": job_namekey,
                    "lastAssignedRobot": robot_id,
                    "status": "InProgress",
                    "jobType": "M",
                    "queuedTimestamp": {"millis": str(now_ms)},
                    "upd": {"millis": str(now_ms)}
                }
        return None

    async def get_job_details_by_job_id(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Returns job details for the given ID (searches by matching namekey)."""
        # Try finding by namekey first
        namekey = job_id
        details = await self.get_job_details_by_namekey(namekey)
        if details:
            return details
        
        # Fallback: search all jobs for matching jobId field
        for job in self._jobs_db.values():
            if job.get("jobId") == job_id:
                return job
        return None
