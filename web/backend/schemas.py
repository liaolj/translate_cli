from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .models import FileProgress, JobProgress


class FileProgressSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    path: str
    status: str
    error: Optional[str] = None
    updated_at: datetime

    @classmethod
    def from_model(cls, model: FileProgress) -> "FileProgressSchema":
        return cls(
            path=model.path,
            status=model.status.value,
            error=model.error,
            updated_at=model.updated_at,
        )


class JobProgressSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    job_id: str = Field(alias="id")
    repo_url: str
    branch: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    total_files: int
    completed_files: int
    failed_files: int
    percent_complete: float
    eta_seconds: Optional[float]
    log_path: Optional[str]
    output_path: Optional[str]
    extensions: List[str]
    error_message: Optional[str]
    log_excerpt: Optional[str]
    files: List[FileProgressSchema]

    @classmethod
    def from_model(cls, model: JobProgress) -> "JobProgressSchema":
        files = [FileProgressSchema.from_model(fp) for fp in model.file_states.values()]
        files.sort(key=lambda item: item.path)
        return cls(
            job_id=model.job_id,
            repo_url=model.repo_url,
            status=model.status.value,
            created_at=model.created_at,
            updated_at=model.updated_at,
            started_at=model.started_at,
            finished_at=model.finished_at,
            total_files=model.total_files,
            completed_files=model.completed_files,
            failed_files=model.failed_files,
            percent_complete=model.percent_complete,
            eta_seconds=model.eta_seconds,
            log_path=model.log_path,
            output_path=model.output_path,
            branch=model.branch,
            extensions=model.extensions,
            error_message=model.error_message,
            log_excerpt=model.log_excerpt,
            files=files,
        )


class JobListItemSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    job_id: str = Field(alias="id")
    repo_url: str
    branch: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime
    total_files: int
    completed_files: int
    failed_files: int
    percent_complete: float
    eta_seconds: Optional[float]
    log_excerpt: Optional[str]

    @classmethod
    def from_model(cls, model: JobProgress) -> "JobListItemSchema":
        return cls(
            job_id=model.job_id,
            repo_url=model.repo_url,
            branch=model.branch,
            status=model.status.value,
            created_at=model.created_at,
            updated_at=model.updated_at,
            total_files=model.total_files,
            completed_files=model.completed_files,
            failed_files=model.failed_files,
            percent_complete=model.percent_complete,
            eta_seconds=model.eta_seconds,
            log_excerpt=model.log_excerpt,
        )


class HistoryResponse(BaseModel):
    items: List[JobListItemSchema]
    total: int
    limit: int
    offset: int


class CreateJobRequest(BaseModel):
    repo_url: str
    extensions: List[str]
    output_subdir: Optional[str] = None
    branch: Optional[str] = None


class CreateJobResponse(BaseModel):
    job: JobProgressSchema


class ErrorResponse(BaseModel):
    detail: str
