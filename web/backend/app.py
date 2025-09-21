from __future__ import annotations

import asyncio
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .jobs import JobManager, JobNotFoundError
from .schemas import (
    CreateJobRequest,
    CreateJobResponse,
    ErrorResponse,
    HistoryResponse,
    JobListItemSchema,
    JobProgressSchema,
)
from .settings import AppSettings


def get_app_settings() -> AppSettings:
    return AppSettings.load()


def get_job_manager(settings: AppSettings = Depends(get_app_settings)) -> JobManager:
    # FastAPI dependency will cache single instance per request but we want singleton per process.
    if not hasattr(get_job_manager, "_instance"):
        get_job_manager._instance = JobManager(settings)  # type: ignore[attr-defined]
    return get_job_manager._instance  # type: ignore[attr-defined]


app = FastAPI(title="Transfold Web API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/jobs", response_model=CreateJobResponse, responses={400: {"model": ErrorResponse}})
async def create_job(
    payload: CreateJobRequest,
    manager: JobManager = Depends(get_job_manager),
) -> CreateJobResponse:
    if not payload.repo_url.startswith("https://github.com/"):
        raise HTTPException(status_code=400, detail="仅支持 GitHub HTTPS 仓库地址")
    extensions = [ext.lstrip(".").lower() for ext in payload.extensions if ext.strip()]
    if not extensions:
        raise HTTPException(status_code=400, detail="请至少选择一个文件扩展名")
    branch = payload.branch.strip() if payload.branch else None
    if branch and any(ch.isspace() for ch in branch):
        raise HTTPException(status_code=400, detail="分支名称不能包含空白字符")
    job_progress = await manager.create_job(
        repo_url=payload.repo_url,
        extensions=extensions,
        output_subdir=payload.output_subdir,
        branch=branch,
    )
    return CreateJobResponse(job=JobProgressSchema.from_model(job_progress))


@app.get("/api/jobs/{job_id}", response_model=JobProgressSchema, responses={404: {"model": ErrorResponse}})
async def get_job(
    job_id: str,
    manager: JobManager = Depends(get_job_manager),
) -> JobProgressSchema:
    try:
        progress = await manager.get_job(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail="任务不存在") from None
    return JobProgressSchema.from_model(progress)


@app.get("/api/jobs", response_model=HistoryResponse)
async def list_jobs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: Optional[str] = None,
    manager: JobManager = Depends(get_job_manager),
) -> HistoryResponse:
    jobs = await manager.list_jobs(limit=limit, offset=offset, search=search)
    total = await manager.count_jobs(search=search)
    items = [JobListItemSchema.from_model(job) for job in jobs]
    return HistoryResponse(items=items, total=total, limit=limit, offset=offset)


@app.post("/api/jobs/{job_id}/rerun", response_model=CreateJobResponse, responses={404: {"model": ErrorResponse}})
async def rerun_job(
    job_id: str,
    manager: JobManager = Depends(get_job_manager),
) -> CreateJobResponse:
    try:
        progress = await manager.rerun_job(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail="任务不存在") from None
    return CreateJobResponse(job=JobProgressSchema.from_model(progress))


@app.delete(
    "/api/jobs/{job_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={404: {"model": ErrorResponse}, 400: {"model": ErrorResponse}},
)
async def delete_job(
    job_id: str,
    manager: JobManager = Depends(get_job_manager),
) -> Response:
    try:
        await manager.delete_job(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail="任务不存在") from None
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/jobs/{job_id}/tree")
async def get_output_tree(
    job_id: str,
    manager: JobManager = Depends(get_job_manager),
) -> JSONResponse:
    progress = await manager.get_job(job_id)
    if not progress.output_path:
        raise HTTPException(status_code=404, detail="任务尚未产出文件")
    root = Path(progress.output_path)
    if not root.exists():
        raise HTTPException(status_code=404, detail="输出目录不存在")

    def _scan() -> List[dict]:
        entries: List[dict] = [{"path": ".", "type": "directory"}]
        for path in sorted(root.rglob("*")):
            rel = path.relative_to(root).as_posix()
            entries.append({
                "path": rel,
                "type": "directory" if path.is_dir() else "file",
            })
        return entries

    entries = await asyncio.to_thread(_scan)
    return JSONResponse({"entries": entries})


@app.get("/api/jobs/{job_id}/preview")
async def preview_file(
    job_id: str,
    path: str = Query(..., description="输出目录内的相对路径"),
    manager: JobManager = Depends(get_job_manager),
) -> JSONResponse:
    progress = await manager.get_job(job_id)
    if not progress.output_path:
        raise HTTPException(status_code=404, detail="任务尚未产出文件")
    root = Path(progress.output_path).resolve()
    target = (root / path).resolve()
    if not str(target).startswith(str(root)):
        raise HTTPException(status_code=400, detail="非法路径")
    if not target.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    if target.is_dir():
        raise HTTPException(status_code=400, detail="无法预览目录")

    def _read() -> str:
        return target.read_text(encoding="utf-8")

    content = await asyncio.to_thread(_read)
    return JSONResponse({"path": path, "content": content})


@app.get("/api/jobs/{job_id}/log")
async def download_log(
    job_id: str,
    manager: JobManager = Depends(get_job_manager),
) -> FileResponse:
    progress = await manager.get_job(job_id)
    if not progress.log_path:
        raise HTTPException(status_code=404, detail="日志不存在")
    path = Path(progress.log_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="日志文件不存在")
    return FileResponse(path)


__all__ = ["app"]
