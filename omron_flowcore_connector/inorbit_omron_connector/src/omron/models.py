# SPDX-FileCopyrightText: 2025 InOrbit, Inc.
#
# SPDX-License-Identifier: MIT

"""Data models for FlowCore API."""

from typing import List, Any, Optional
from pydantic import BaseModel

class OmronUpdate(BaseModel):
    millis: int

class RobotResponse(BaseModel):
    namekey: str
    upd: OmronUpdate
    status: str
    subStatus: str
    ipAddress: str | None = None

class DataStoreResponse(BaseModel):
    namekey: str
    upd: OmronUpdate
    value: Any

class JobRequestDetail(BaseModel):
    pickupGoal: str | None = None
    dropoffGoal: str | None = None
    priority: int | None = 10

class JobRequest(BaseModel):
    namekey: str
    jobId: str
    defaultPriority: bool
    details: List[JobRequestDetail]

class JobCancelByRobotName(BaseModel):
    robot: str
    cancelReason: str

class JobCancelByJobNamekey(BaseModel):
    jobNamekey: str
    cancelReason: str

class JobSegmentResponse(BaseModel):
    namekey: str
    seq: int
    segmentId: str
    segmentType: str
    status: str
    subStatus: str
    job: str
    robot: Optional[str] = None
    linkedJobSegment: Optional[str] = None
    goalName: str
    priority: int
    completedTimestamp: Optional[OmronUpdate] = None
    cancelReason: Optional[str] = None

class JobResponse(BaseModel):
    namekey: str
    jobId: str
    jobType: str
    completedTimestamp: Optional[OmronUpdate] = None
    status: str
    linkedJob: Optional[str] = None
    failCount: Optional[int] = None
    lastAssignedRobot: str
    cancelReason: Optional[str] = None

class DropoffJob(BaseModel):
    namekey: str
    jobId: str
    priority: int
    goal: str
    robot: str
