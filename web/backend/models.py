from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class FileStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class FileProgress:
    path: str
    status: FileStatus = FileStatus.PENDING
    error: Optional[str] = None
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class JobProgress:
    job_id: str
    repo_url: str
    created_at: datetime
    updated_at: datetime
    status: JobStatus = JobStatus.QUEUED
    total_files: int = 0
    completed_files: int = 0
    failed_files: int = 0
    percent_complete: float = 0.0
    eta_seconds: Optional[float] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    log_path: Optional[str] = None
    output_path: Optional[str] = None
    output_subdir: Optional[str] = None
    branch: Optional[str] = None
    extensions: List[str] = field(default_factory=list)
    error_message: Optional[str] = None
    log_excerpt: Optional[str] = None
    file_states: Dict[str, FileProgress] = field(default_factory=dict)


__all__ = [
    "JobStatus",
    "FileStatus",
    "FileProgress",
    "JobProgress",
]
