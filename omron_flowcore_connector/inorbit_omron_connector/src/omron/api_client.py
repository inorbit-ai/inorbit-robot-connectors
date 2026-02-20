# SPDX-FileCopyrightText: 2026 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

import httpx
import logging
import json
from typing import List, Dict, Any, Optional, AsyncIterator
from .models import (
    DataStoreResponse, 
    RobotResponse
)

LOGGER = logging.getLogger(__name__)

class OmronApiClient:
    """
    Omron API Client for FlowCore.
    """
    def __init__(self, config: Dict[str, Any]):
        self.base_url = config.url.rstrip("/")
        self.username = config.username
        self.password = config.password
        self.verify_ssl = config.verify_ssl
        self.client: Optional[httpx.AsyncClient] = None

    async def connect(self) -> bool:
        """Initializes the httpx AsyncClient."""
        if not self.client:
            self.client = httpx.AsyncClient(
                base_url=self.base_url,
                auth=(self.username, self.password),
                verify=self.verify_ssl,
                timeout=10.0
            )
        return True

    async def close(self):
        """Closes the httpx AsyncClient."""
        if self.client:
            await self.client.aclose()
            self.client = None

    async def get_fleet_state(self) -> List[RobotResponse]:
        """Fetches fleet state from /Robot/UpdatedSince."""
        if not self.client:
            await self.connect()
        
        try:
            response = await self.client.get("/Robot/UpdatedSince?sinceTime=0")

            response.raise_for_status()
            data = response.json()
            return [RobotResponse(**r) for r in data]
        except Exception as e:
            LOGGER.error(f"Error fetching fleet state: {e}")
            return []

    async def get_data_store_value(self, key: str, robot_id: str) -> List[DataStoreResponse]:
        """Fetches data store values for a specific key."""
        if not self.client:
            await self.connect()
        
        mappedKey = {
            "StateOfCharge": "BatteryStateOfCharge",
            "PoseX": "RobotX",
            "PoseY": "RobotY",
            "PoseTh": "RobotTh",
            "RobotIP": "RobotIP"
        }

        try:
            # The endpoint structure based on the curl: /DataStoreValueLatest/{key}
            url = f"/DataStoreValueLatest/{mappedKey[key]}:{robot_id}"
            response = await self.client.get(url)

            response.raise_for_status()
            data = response.json()
            
            # If robot_id is not '*', we might need to filter the results
            # but usually the API returns all robots for that key.
            results = [DataStoreResponse(**item) for item in data]
            if robot_id != "*":
                results = [r for r in results if r.namekey.endswith(f":{robot_id}")]
            
            return results
        except Exception as e:
            LOGGER.error(f"Error fetching data store value for {key}: {e}")
            return []

    async def create_job(self, job_request: Dict[str, Any]) -> bool:
        if not self.client:
            await self.connect()
        
        try:
            response = await self.client.post("/JobRequest", json=job_request)
            response.raise_for_status()
            return True
        except Exception as e:
            LOGGER.error(f"Error creating job: {e}")
            return False

    async def stop(self, job_cancel: Dict[str, Any]) -> bool:
        if not self.client:
            await self.connect()
        
        try:
            response = await self.client.post("/JobCancel", json=job_cancel)
            response.raise_for_status()
            return True
        except Exception as e:
            LOGGER.error(f"Error canceling job: {e}")
            return False

    async def get_job_stream(self) -> AsyncIterator[Dict[str, Any]]:
        """Streams events from /Job/Stream."""
        if not self.client:
            await self.connect()
        
        try:
            async with self.client.stream(
                "GET",
                "/Job/Stream",
                headers={"Accept": "text/event-stream"},
                timeout=None  # No timeout for streaming
            ) as response:
                response.raise_for_status()
                
                async for line in response.aiter_lines():
                    line = line.strip()
                    
                    # SSE format: "data: {json}"
                    if line.startswith("data:"):
                        data_str = line[5:].strip()  # Remove "data:" prefix
                        
                        if data_str:
                            try:
                                event_data = json.loads(data_str)
                                yield event_data
                            except json.JSONDecodeError as e:
                                LOGGER.warning(f"Failed to parse SSE data: {data_str}, error: {e}")
                    # Ignore empty lines and comments
                    elif line.startswith(":") or not line:
                        continue
                        
        except httpx.HTTPStatusError as e:
            LOGGER.error(f"HTTP error in job stream: {e}")
            raise
        except Exception as e:
            LOGGER.error(f"Error in job stream: {e}")
            raise

    async def get_job_segment_stream(self) -> AsyncIterator[Dict[str, Any]]:
        """Streams events from /JobSegment/Stream."""
        if not self.client:
            await self.connect()
        
        try:
            async with self.client.stream(
                "GET",
                "/JobSegment/Stream",
                headers={"Accept": "text/event-stream"},
                timeout=None  # No timeout for streaming
            ) as response:
                response.raise_for_status()
                
                async for line in response.aiter_lines():
                    line = line.strip()
                    
                    # SSE format: "data: {json}"
                    if line.startswith("data:"):
                        data_str = line[5:].strip()  # Remove "data:" prefix
                        
                        if data_str:
                            try:
                                event_data = json.loads(data_str)
                                yield event_data
                            except json.JSONDecodeError as e:
                                LOGGER.warning(f"Failed to parse SSE data: {data_str}, error: {e}")
                    # Ignore empty lines and comments
                    elif line.startswith(":") or not line:
                        continue
                        
        except httpx.HTTPStatusError as e:
            LOGGER.error(f"HTTP error in job segment stream: {e}")
            raise
        except Exception as e:
            LOGGER.error(f"Error in job segment stream: {e}")
            raise

    async def get_job_segment_list(self, job_namekey: str) -> List[Dict[str, Any]]:
        if not self.client:
            await self.connect()
        
        try:
            response = await self.client.get(f"/JobSegment/ByJob/{job_namekey}")
            response.raise_for_status()
            data = response.json()
            return data
        except Exception as e:
            LOGGER.error(f"Error fetching fleet state: {e}")
            return []
    
    async def get_job_details_by_job_id(self, job_id: str) -> Optional[Dict[str, Any]]:
        if not self.client:
            await self.connect()
        
        try:
            response = await self.client.get(f"/Job/ByJobId/{job_id}")
            response.raise_for_status()
            data = response.json()
            return data[0] if data and len(data) > 0 else None
        except Exception as e:
            LOGGER.error(f"Error fetching job details: {e}")
            return None

    async def get_job_details_by_namekey(self, job_namekey: str) -> Optional[Dict[str, Any]]:
        if not self.client:
            await self.connect()
        
        try:
            response = await self.client.get(f"/Job/ByKey/{job_namekey}")
            response.raise_for_status()
            data = response.json()
            return data
        except Exception as e:
            LOGGER.error(f"Error fetching job details: {e}")
            return None

    async def create_dropoff(self, dropoff_request: Dict[str, Any]) -> bool:
        if not self.client:
            await self.connect()
        
        try:
            response = await self.client.post("/Dropoff", json=dropoff_request)
            response.raise_for_status()
            return True
        except Exception as e:
            LOGGER.error(f"Error creating dropoff job: {e}")
            return False
