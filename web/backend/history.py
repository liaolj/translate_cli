from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .models import FileProgress, FileStatus, JobProgress, JobStatus


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class HistoryStore:
    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._lock = threading.Lock()
        if not db_path.parent.exists():
            db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn, conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    repo_url TEXT NOT NULL,
                    extensions TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    total_files INTEGER NOT NULL DEFAULT 0,
                    completed_files INTEGER NOT NULL DEFAULT 0,
                    failed_files INTEGER NOT NULL DEFAULT 0,
                    percent REAL NOT NULL DEFAULT 0,
                    eta_seconds REAL,
                    log_path TEXT,
                    output_path TEXT,
                    output_subdir TEXT,
                    branch TEXT,
                    error_message TEXT,
                    log_excerpt TEXT,
                    files_json TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_repo_url ON jobs(repo_url)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)"
            )
            columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(jobs)")
            }
            if "output_subdir" not in columns:
                conn.execute("ALTER TABLE jobs ADD COLUMN output_subdir TEXT")
            if "branch" not in columns:
                conn.execute("ALTER TABLE jobs ADD COLUMN branch TEXT")

    def upsert_job(self, progress: JobProgress) -> None:
        payload = self._to_row(progress)
        with self._lock, self._connect() as conn, conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    id, repo_url, extensions, status, created_at, updated_at,
                    started_at, finished_at, total_files, completed_files, failed_files,
                    percent, eta_seconds, log_path, output_path, error_message,
                    output_subdir, branch, log_excerpt, files_json
                ) VALUES (
                    :id, :repo_url, :extensions, :status, :created_at, :updated_at,
                    :started_at, :finished_at, :total_files, :completed_files, :failed_files,
                    :percent, :eta_seconds, :log_path, :output_path, :error_message,
                    :output_subdir, :branch, :log_excerpt, :files_json
                )
                ON CONFLICT(id) DO UPDATE SET
                    repo_url=excluded.repo_url,
                    extensions=excluded.extensions,
                    status=excluded.status,
                    created_at=excluded.created_at,
                    updated_at=excluded.updated_at,
                    started_at=excluded.started_at,
                    finished_at=excluded.finished_at,
                    total_files=excluded.total_files,
                    completed_files=excluded.completed_files,
                    failed_files=excluded.failed_files,
                    percent=excluded.percent,
                    eta_seconds=excluded.eta_seconds,
                    log_path=excluded.log_path,
                    output_path=excluded.output_path,
                    output_subdir=excluded.output_subdir,
                    branch=excluded.branch,
                    error_message=excluded.error_message,
                    log_excerpt=excluded.log_excerpt,
                    files_json=excluded.files_json
                """,
                payload,
            )

    def update_fields(self, job_id: str, **fields: object) -> None:
        if not fields:
            return
        allowed = {
            "repo_url",
            "extensions",
            "status",
            "created_at",
            "updated_at",
            "started_at",
            "finished_at",
            "total_files",
            "completed_files",
            "failed_files",
            "percent",
            "eta_seconds",
            "log_path",
            "output_path",
            "output_subdir",
            "branch",
            "error_message",
            "log_excerpt",
            "files_json",
        }
        assignments = []
        params: Dict[str, object] = {"job_id": job_id}
        for key, value in fields.items():
            if key not in allowed:
                continue
            assignments.append(f"{key} = :{key}")
            params[key] = value
        if not assignments:
            return
        assignments.append("updated_at = :updated_at")
        params.setdefault("updated_at", _utc_now().isoformat())
        sql = f"UPDATE jobs SET {', '.join(assignments)} WHERE id = :job_id"
        with self._lock, self._connect() as conn, conn:
            conn.execute(sql, params)

    def get_job(self, job_id: str) -> Optional[JobProgress]:
        with self._connect() as conn, conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        return self._from_row(row)

    def delete_job(self, job_id: str) -> None:
        with self._lock, self._connect() as conn, conn:
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

    def list_jobs(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        search: Optional[str] = None,
        status: Optional[JobStatus] = None,
    ) -> List[JobProgress]:
        clauses: List[str] = []
        params: List[object] = []
        if search:
            clauses.append("repo_url LIKE ?")
            params.append(f"%{search}%")
        if status:
            clauses.append("status = ?")
            params.append(status.value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql = (
            "SELECT * FROM jobs"
            f"{where}"
            " ORDER BY datetime(created_at) DESC"
            " LIMIT ? OFFSET ?"
        )
        params.extend([limit, offset])
        with self._connect() as conn, conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._from_row(row) for row in rows]

    def count_jobs(
        self,
        *,
        search: Optional[str] = None,
        status: Optional[JobStatus] = None,
    ) -> int:
        clauses: List[str] = []
        params: List[object] = []
        if search:
            clauses.append("repo_url LIKE ?")
            params.append(f"%{search}%")
        if status:
            clauses.append("status = ?")
            params.append(status.value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql = f"SELECT COUNT(*) FROM jobs{where}"
        with self._connect() as conn, conn:
            row = conn.execute(sql, params).fetchone()
        return int(row[0]) if row else 0

    def _to_row(self, progress: JobProgress) -> Dict[str, object]:
        files_payload = [
            {
                "path": fp.path,
                "status": fp.status.value,
                "error": fp.error,
                "updated_at": fp.updated_at.isoformat(),
            }
            for fp in progress.file_states.values()
        ]
        return {
            "id": progress.job_id,
            "repo_url": progress.repo_url,
            "extensions": json.dumps(progress.extensions),
            "status": progress.status.value,
            "created_at": progress.created_at.isoformat(),
            "updated_at": progress.updated_at.isoformat(),
            "started_at": progress.started_at.isoformat() if progress.started_at else None,
            "finished_at": progress.finished_at.isoformat() if progress.finished_at else None,
            "total_files": progress.total_files,
            "completed_files": progress.completed_files,
            "failed_files": progress.failed_files,
            "percent": progress.percent_complete,
            "eta_seconds": progress.eta_seconds,
            "log_path": progress.log_path,
            "output_path": progress.output_path,
            "output_subdir": progress.output_subdir,
            "branch": progress.branch,
            "error_message": progress.error_message,
            "log_excerpt": progress.log_excerpt,
            "files_json": json.dumps(files_payload),
        }

    def _from_row(self, row: sqlite3.Row) -> JobProgress:
        files_json = row["files_json"]
        file_states: Dict[str, FileProgress] = {}
        if files_json:
            try:
                decoded = json.loads(files_json)
            except json.JSONDecodeError:
                decoded = []
            for item in decoded:
                path = item.get("path")
                if not path:
                    continue
                status_value = item.get("status", FileStatus.PENDING.value)
                status = FileStatus(status_value)
                updated_raw = item.get("updated_at")
                try:
                    updated_at = datetime.fromisoformat(updated_raw) if updated_raw else _utc_now()
                except ValueError:
                    updated_at = _utc_now()
                file_states[path] = FileProgress(
                    path=path,
                    status=status,
                    error=item.get("error"),
                    updated_at=updated_at,
                )
        created_at = datetime.fromisoformat(row["created_at"]) if row["created_at"] else _utc_now()
        updated_at = datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else created_at
        started_at = row["started_at"]
        finished_at = row["finished_at"]

        return JobProgress(
            job_id=row["id"],
            repo_url=row["repo_url"],
            created_at=created_at,
            updated_at=updated_at,
            status=JobStatus(row["status"]),
            total_files=row["total_files"] or 0,
            completed_files=row["completed_files"] or 0,
            failed_files=row["failed_files"] or 0,
            percent_complete=row["percent"] or 0.0,
            eta_seconds=row["eta_seconds"],
            started_at=datetime.fromisoformat(started_at) if started_at else None,
            finished_at=datetime.fromisoformat(finished_at) if finished_at else None,
            log_path=row["log_path"],
            output_path=row["output_path"],
            output_subdir=row["output_subdir"],
            branch=row["branch"],
            extensions=json.loads(row["extensions"]) if row["extensions"] else [],
            error_message=row["error_message"],
            log_excerpt=row["log_excerpt"],
            file_states=file_states,
        )


__all__ = ["HistoryStore"]
