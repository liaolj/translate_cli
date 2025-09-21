from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from transfold.cli import Settings, read_and_segment_async
from transfold.files import atomic_write, gather_files
from transfold.translator import OpenRouterTranslator, TranslationError

from .cache import CacheKey, TranslationCache
from .history import HistoryStore
from .models import FileProgress, FileStatus, JobProgress, JobStatus
from .settings import AppSettings


class JobNotFoundError(KeyError):
    pass


class TranslationJob:
    def __init__(
        self,
        *,
        repo_url: str,
        extensions: List[str],
        settings: AppSettings,
        history: HistoryStore,
        cache: TranslationCache,
        output_subdir: Optional[str] = None,
        branch: Optional[str] = None,
    ) -> None:
        self.id: str = uuid.uuid4().hex
        self.repo_url = repo_url
        self.extensions = [ext.lstrip(".").lower() for ext in extensions if ext]
        self.settings = settings
        self.history = history
        self.cache = cache
        self.output_subdir = output_subdir.strip() if output_subdir else None
        self.branch = branch.strip() if branch else None
        self.repo_path = settings.repos_root / self.id
        effective_output_root = settings.outputs_root / (self.output_subdir or self.id)
        self.output_path = effective_output_root
        self.log_path = settings.logs_root / f"{self.id}.log"
        self._log_handle = self.log_path.open("a", encoding="utf-8")
        self._lock = asyncio.Lock()
        now = datetime.utcnow()
        self.progress = JobProgress(
            job_id=self.id,
            repo_url=self.repo_url,
            created_at=now,
            updated_at=now,
            status=JobStatus.QUEUED,
            total_files=0,
            completed_files=0,
            failed_files=0,
            percent_complete=0.0,
            eta_seconds=None,
            started_at=None,
            finished_at=None,
            log_path=str(self.log_path),
            output_path=str(self.output_path),
            output_subdir=self.output_subdir,
            branch=self.branch,
            extensions=self.extensions,
            error_message=None,
            log_excerpt=None,
            file_states={},
        )
        self.history.upsert_job(self.progress)
        self._task: Optional[asyncio.Task[None]] = None

    def start(self) -> None:
        loop = asyncio.get_event_loop()
        self._task = loop.create_task(self._run())

    def serialize(self) -> JobProgress:
        return self.progress

    async def _run(self) -> None:
        try:
            await self._update_status(JobStatus.RUNNING)
            self._log("Job started")
            await self._prepare_directories()
            await self._clone_repo()
            files = await self._gather_target_files()
            if not files:
                raise RuntimeError("仓库中没有匹配的文件类型，任务终止")
            await self._initialise_file_states(files)

            api_key = os.getenv("OPENROUTER_API_KEY")
            if not api_key:
                raise RuntimeError("OPENROUTER_API_KEY 未设置，请先配置 .env")

            cli_settings = Settings(
                input_dir=self.repo_path,
                output_dir=self.output_path,
                extensions=self.extensions,
                target_lang=self.settings.target_lang,
                source_lang=self.settings.source_lang,
                model=self.settings.model,
                concurrency=self.settings.concurrency,
                include=[],
                exclude=[],
                max_chars=self.settings.max_chars,
                split_threshold=self.settings.split_threshold,
                chunk_strategy=self.settings.chunk_strategy,
                translate_code=self.settings.translate_code,
                translate_frontmatter=self.settings.translate_frontmatter,
                dry_run=False,
                backup=False,
                stream_writes=False,
                retry=self.settings.retry,
                timeout=self.settings.timeout,
                glossary=None,
                api_key=api_key,
                debug=False,
                batch_chars=self.settings.batch_chars,
                batch_segments=self.settings.batch_segments,
            )

            worker_count = max(1, min(self.settings.concurrency, len(files)))
            translator_kwargs = dict(
                api_key=api_key,
                model=self.settings.model,
                target_lang=self.settings.target_lang,
                source_lang=self.settings.source_lang,
                timeout=self.settings.timeout,
                retry=self.settings.retry,
                concurrency=max(1, self.settings.concurrency // max(1, worker_count)),
                max_batch_chars=self.settings.batch_chars,
                max_batch_segments=self.settings.batch_segments,
            )

            await self._process_files(
                files,
                worker_count,
                translator_kwargs,
                cli_settings,
            )

            self._log("全部文件翻译完成")
            await self._update_status(JobStatus.COMPLETED)
        except Exception as exc:
            await self._record_failure(exc)
        finally:
            self._log_handle.close()
            await self._finalize_log_excerpt()
            self.history.upsert_job(self.progress)

    async def _prepare_directories(self) -> None:
        await asyncio.to_thread(self._cleanup_path, self.repo_path)
        await asyncio.to_thread(self.output_path.mkdir, parents=True, exist_ok=True)

    @staticmethod
    def _cleanup_path(path: Path) -> None:
        if path.exists():
            shutil.rmtree(path)

    async def _clone_repo(self) -> None:
        self._log(
            "开始克隆仓库: "
            f"{self.repo_url}" + (f" 分支 {self.branch}" if self.branch else "")
        )
        cmd = [
            "git",
            "clone",
            "--depth",
            "1",
            "--single-branch",
        ]
        if self.branch:
            cmd.extend(["--branch", self.branch])
        cmd.extend([self.repo_url, str(self.repo_path)])

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            stdout_text = stdout.decode("utf-8", errors="ignore")
            stderr_text = stderr.decode("utf-8", errors="ignore")
            self._log(f"git clone 失败: {stderr_text.strip()}\n{stdout_text.strip()}")
            raise RuntimeError(f"git clone 失败: {stderr_text.strip() or stdout_text.strip()}")
        self._log("仓库克隆完成")

    async def _gather_target_files(self) -> List[Path]:
        def _collect() -> List[Path]:
            files = list(
                gather_files(
                    self.repo_path,
                    extensions=self.extensions,
                )
            )
            files.sort()
            return files

        files = await asyncio.to_thread(_collect)
        self._log(f"发现 {len(files)} 个待翻译文件")
        return files

    async def _initialise_file_states(self, files: List[Path]) -> None:
        async with self._lock:
            now = datetime.utcnow()
            self.progress.started_at = now
            self.progress.total_files = len(files)
            self.progress.file_states = {
                file.relative_to(self.repo_path).as_posix(): FileProgress(
                    path=file.relative_to(self.repo_path).as_posix(),
                    status=FileStatus.PENDING,
                )
                for file in files
            }
            self.progress.updated_at = now
            self.history.upsert_job(self.progress)

    async def _process_files(
        self,
        files: List[Path],
        worker_count: int,
        translator_kwargs: Dict[str, object],
        cli_settings: Settings,
    ) -> None:
        queue: "asyncio.Queue[Path | None]" = asyncio.Queue()
        for file_path in files:
            await queue.put(file_path)
        for _ in range(worker_count):
            await queue.put(None)

        async def worker() -> None:
            translator = OpenRouterTranslator(**translator_kwargs)
            try:
                while True:
                    item = await queue.get()
                    if item is None:
                        queue.task_done()
                        break
                    try:
                        await self._process_file(item, translator, cli_settings)
                    finally:
                        queue.task_done()
            finally:
                await translator.close()

        tasks = [asyncio.create_task(worker()) for _ in range(worker_count)]
        await queue.join()
        for task in tasks:
            await task

    async def _process_file(
        self,
        file_path: Path,
        translator: OpenRouterTranslator,
        cli_settings: Settings,
    ) -> None:
        relative_key = file_path.relative_to(self.repo_path).as_posix()
        await self._mark_file_status(relative_key, FileStatus.IN_PROGRESS)
        try:
            original, segmented, _ = await read_and_segment_async(
                file_path,
                settings=cli_settings,
            )
            destination = self.output_path / relative_key
            content_hash = hashlib.sha256(original.encode("utf-8")).hexdigest()
            cache_key = CacheKey(
                content_hash=content_hash,
                target_lang=self.settings.target_lang,
                model=self.settings.model,
                source_lang=self.settings.source_lang,
            )
            cached = await asyncio.to_thread(self.cache.get, cache_key)
            if cached is not None:
                await asyncio.to_thread(
                    atomic_write,
                    destination,
                    cached,
                    backup=False,
                )
                self._log(f"缓存命中: {relative_key}")
                await self._mark_file_status(relative_key, FileStatus.COMPLETED)
                await self._increment_counts(success=True)
                return

            await translator.translate_segments(segmented.segments)
            rendered = segmented.merge()
            await asyncio.to_thread(
                atomic_write,
                destination,
                rendered,
                backup=False,
            )
            await asyncio.to_thread(self.cache.set, cache_key, rendered)
            await self._mark_file_status(relative_key, FileStatus.COMPLETED)
            await self._increment_counts(success=True)
        except TranslationError as exc:
            self._log(f"翻译失败 {relative_key}: {exc}")
            await self._mark_file_status(relative_key, FileStatus.FAILED, str(exc))
            await self._increment_counts(success=False)
        except Exception as exc:
            self._log(f"处理文件失败 {relative_key}: {exc}")
            await self._mark_file_status(relative_key, FileStatus.FAILED, str(exc))
            await self._increment_counts(success=False)

    async def _increment_counts(self, *, success: bool) -> None:
        async with self._lock:
            if success:
                self.progress.completed_files += 1
            else:
                self.progress.failed_files += 1
            processed = self.progress.completed_files + self.progress.failed_files
            if self.progress.total_files:
                self.progress.percent_complete = round(
                    processed / self.progress.total_files * 100, 2
                )
            else:
                self.progress.percent_complete = 0.0
            if processed and self.progress.started_at:
                elapsed = (datetime.utcnow() - self.progress.started_at).total_seconds()
                average = elapsed / processed
                if self.progress.total_files:
                    remaining = max(self.progress.total_files - processed, 0)
                    self.progress.eta_seconds = round(max(average * remaining, 0.0), 2)
            self.progress.updated_at = datetime.utcnow()
            self.history.upsert_job(self.progress)

    async def _mark_file_status(
        self,
        relative_key: str,
        status: FileStatus,
        error: Optional[str] = None,
    ) -> None:
        async with self._lock:
            state = self.progress.file_states.get(relative_key)
            if state is None:
                state = FileProgress(path=relative_key)
                self.progress.file_states[relative_key] = state
            state.status = status
            state.error = error
            state.updated_at = datetime.utcnow()
            self.progress.updated_at = state.updated_at
            self.history.upsert_job(self.progress)

    async def _update_status(self, status: JobStatus) -> None:
        async with self._lock:
            self.progress.status = status
            self.progress.updated_at = datetime.utcnow()
            if status == JobStatus.RUNNING and self.progress.started_at is None:
                self.progress.started_at = self.progress.updated_at
            if status in {JobStatus.COMPLETED, JobStatus.FAILED}:
                self.progress.finished_at = self.progress.updated_at
                self.progress.eta_seconds = 0.0
            self.history.upsert_job(self.progress)

    async def _record_failure(self, exc: Exception) -> None:
        message = str(exc)
        self._log(f"任务失败: {message}")
        await self._update_status(JobStatus.FAILED)
        async with self._lock:
            self.progress.error_message = message
            self.progress.updated_at = datetime.utcnow()
            self.history.upsert_job(self.progress)

    async def _finalize_log_excerpt(self) -> None:
        def _read_excerpt() -> str:
            if not self.log_path.exists():
                return ""
            lines: List[str] = []
            with self.log_path.open("r", encoding="utf-8") as handle:
                for _ in range(50):
                    line = handle.readline()
                    if not line:
                        break
                    lines.append(line.rstrip())
            return "\n".join(lines)

        excerpt = await asyncio.to_thread(_read_excerpt)
        async with self._lock:
            self.progress.log_excerpt = excerpt
            self.progress.updated_at = datetime.utcnow()
            self.history.upsert_job(self.progress)

    def _log(self, message: str) -> None:
        timestamp = datetime.utcnow().isoformat()
        self._log_handle.write(f"[{timestamp}] {message}\n")
        self._log_handle.flush()


class JobManager:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.history = HistoryStore(settings.history_db)
        self.cache = TranslationCache(settings.cache_db)
        self._jobs: Dict[str, TranslationJob] = {}
        self._lock = asyncio.Lock()

    async def create_job(
        self,
        *,
        repo_url: str,
        extensions: List[str],
        output_subdir: Optional[str] = None,
        branch: Optional[str] = None,
    ) -> JobProgress:
        job = TranslationJob(
            repo_url=repo_url,
            extensions=extensions,
            settings=self.settings,
            history=self.history,
            cache=self.cache,
            output_subdir=output_subdir,
            branch=branch,
        )
        async with self._lock:
            self._jobs[job.id] = job
        job.start()
        return job.serialize()

    async def get_job(self, job_id: str) -> JobProgress:
        async with self._lock:
            job = self._jobs.get(job_id)
        if job:
            return job.serialize()
        record = await asyncio.to_thread(self.history.get_job, job_id)
        if record is None:
            raise JobNotFoundError(job_id)
        return record

    async def list_jobs(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        search: Optional[str] = None,
    ) -> List[JobProgress]:
        return await asyncio.to_thread(
            self.history.list_jobs,
            limit=limit,
            offset=offset,
            search=search,
        )

    async def count_jobs(
        self,
        *,
        search: Optional[str] = None,
    ) -> int:
        return await asyncio.to_thread(
            self.history.count_jobs,
            search=search,
        )

    async def delete_job(self, job_id: str) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
        if job and job.progress.status in {JobStatus.RUNNING, JobStatus.QUEUED}:
            raise RuntimeError("运行中的任务暂不支持删除")
        record = await asyncio.to_thread(self.history.get_job, job_id)
        if not record:
            raise JobNotFoundError(job_id)
        await asyncio.to_thread(self._cleanup_artifacts, record)
        await asyncio.to_thread(self.history.delete_job, job_id)

    async def rerun_job(self, job_id: str) -> JobProgress:
        record = await asyncio.to_thread(self.history.get_job, job_id)
        if not record:
            raise JobNotFoundError(job_id)
        return await self.create_job(
            repo_url=record.repo_url,
            extensions=record.extensions,
            output_subdir=record.output_subdir,
            branch=record.branch,
        )

    @staticmethod
    def _cleanup_artifacts(record: JobProgress) -> None:
        for path_str in (record.log_path, record.output_path):
            if not path_str:
                continue
            path = Path(path_str)
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            elif path.exists():
                path.unlink(missing_ok=True)


__all__ = ["JobManager", "JobNotFoundError"]
