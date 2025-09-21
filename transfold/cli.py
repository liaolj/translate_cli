from __future__ import annotations

import argparse
import asyncio
import os
import queue
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Literal

from .chunking import SegmentedDocument, segment_document
from .config import merge_config, load_config, load_env_file
from .files import atomic_write, gather_files, read_glossary, read_text, ensure_parent
from .progress import tqdm
from .translator import OpenRouterTranslator, TranslationError


DEFAULT_MODEL = "openrouter/auto"
DEFAULT_MAX_CHARS = 4000
DEFAULT_TIMEOUT = 60.0
DEFAULT_RETRY = 3
DEFAULT_BATCH_CHARS = 16000
DEFAULT_BATCH_SEGMENTS = 6


@dataclass
class Settings:
    input_dir: Path
    output_dir: Optional[Path]
    extensions: List[str]
    target_lang: str
    source_lang: str
    model: str
    concurrency: int
    include: List[str]
    exclude: List[str]
    max_chars: int
    split_threshold: Optional[int]
    chunk_strategy: str
    translate_code: bool
    translate_frontmatter: bool
    dry_run: bool
    backup: bool
    stream_writes: bool
    retry: int
    timeout: float
    glossary: Optional[Path]
    api_key: str
    debug: bool
    batch_chars: int
    batch_segments: int


WriteMode = Literal["replace", "append"]
WriteTask = tuple[Path, str, bool, WriteMode]


class WriterThread:
    _SENTINEL: WriteTask | None = None

    def __init__(self) -> None:
        self._queue: "queue.Queue[WriteTask | None]" = queue.Queue()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._backed_up: set[Path] = set()

    def start(self) -> None:
        self._thread.start()

    def submit(self, task: WriteTask) -> None:
        self._queue.put(task)

    def close(self) -> None:
        self._queue.put(self._SENTINEL)
        self._queue.join()
        self._thread.join()

    def _worker(self) -> None:
        while True:
            task = self._queue.get()
            if task is self._SENTINEL:
                self._queue.task_done()
                break
            path, content, backup, mode = task
            try:
                if mode == "append":
                    ensure_parent(path)
                    with path.open("a", encoding="utf-8", newline="") as handle:
                        handle.write(content)
                    continue

                effective_backup = backup and path not in self._backed_up
                atomic_write(path, content, backup=effective_backup)
                if effective_backup:
                    self._backed_up.add(path)
            except Exception as exc:  # pragma: no cover - worker should not raise
                print(f"Failed to write {path}: {exc}", file=sys.stderr)
            finally:
                self._queue.task_done()

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Transfold – translate Markdown at scale using OpenRouter")
    parser.add_argument("--config", help="Path to a configuration file", default=None)
    parser.add_argument(
        "--env-file",
        help="Path to a .env file containing OpenRouter credentials",
        default=None,
    )
    parser.add_argument("--input", help="Input directory", default=None)
    parser.add_argument("--output", help="Output directory (mirror structure)")
    parser.add_argument("--ext", action="append", help="File extensions to include (comma separated)", default=None)
    parser.add_argument("--target-lang", help="Target language code")
    parser.add_argument("--source-lang", help="Source language code or 'auto'", default=None)
    parser.add_argument("--model", help="OpenRouter model identifier", default=None)
    parser.add_argument("--concurrency", type=int, help="Number of concurrent API calls", default=None)
    parser.add_argument("--include", action="append", help="Glob pattern to explicitly include", default=None)
    parser.add_argument("--exclude", action="append", help="Glob pattern to exclude", default=None)
    parser.add_argument("--max-chars", type=int, help="Maximum characters per translation chunk", default=None)
    parser.add_argument("--chunk-strategy", help="Chunking strategy", default=None)
    parser.add_argument(
        "--translate-code",
        action=argparse.BooleanOptionalAction,
        help="Translate fenced code blocks as well",
        default=None,
    )
    parser.add_argument(
        "--translate-frontmatter",
        action=argparse.BooleanOptionalAction,
        help="Translate YAML front matter",
        default=None,
    )
    parser.add_argument("--dry-run", action="store_true", help="List files and segments without translating")
    parser.add_argument("--no-backup", action="store_true", help="Do not create .bak files when overwriting input")
    parser.add_argument("--overwrite", action="store_true", help="Alias for --no-backup")
    parser.add_argument("--retry", type=int, help="Maximum retry attempts", default=None)
    parser.add_argument("--timeout", type=float, help="API request timeout in seconds", default=None)
    parser.add_argument("--glossary", help="Glossary file (JSON or CSV)", default=None)
    parser.add_argument(
        "--stream-writes",
        action=argparse.BooleanOptionalAction,
        help="Write translated output after each segment instead of once per document",
        default=None,
    )
    parser.add_argument("--batch-chars", type=int, help="Maximum characters per API request batch", default=None)
    parser.add_argument("--batch-segments", type=int, help="Maximum segments per API request batch", default=None)
    parser.add_argument("--api-key", help="OpenRouter API key", default=None)
    parser.add_argument("--debug", action="store_true", help="Print OpenRouter request/response debug information")
    return parser


async def read_and_segment_async(
    path: Path,
    *,
    settings: "Settings",
    read_text_fn = read_text,
    segment_document_fn = segment_document,
) -> tuple[str, SegmentedDocument, int]:
    """Read and segment a document without blocking the event loop."""

    def _work() -> tuple[str, SegmentedDocument, int]:
        text = read_text_fn(path)
        segmented = segment_document_fn(
            text,
            strategy=settings.chunk_strategy,
            max_chars=settings.max_chars,
            preserve_code=not settings.translate_code,
            preserve_frontmatter=not settings.translate_frontmatter,
            split_threshold=settings.split_threshold,
        )
        translatable = sum(
            1
            for seg in segmented.segments
            if seg.translate and seg.content.strip()
        )
        return text, segmented, translatable

    return await asyncio.to_thread(_work)


def parse_arguments(argv: Optional[List[str]] = None) -> Settings:
    parser = build_parser()
    args = parser.parse_args(argv)

    load_env_file(args.env_file)

    config_data = load_config(args.config)
    explicit_false = {"translate_code", "translate_frontmatter", "stream_writes"}
    cli_overrides = {}
    for key, value in vars(args).items():
        if key == "config":
            continue
        if value is None:
            continue
        if value is False and key not in explicit_false:
            continue
        cli_overrides[key] = value
    merged: Dict[str, object] = merge_config(config_data, cli_overrides)

    input_dir = merged.get("input") or merged.get("input_dir") or args.input
    if not input_dir:
        parser.error("--input is required")
    input_path = Path(input_dir).expanduser().resolve()

    output_dir = merged.get("output")
    output_path = Path(output_dir).expanduser().resolve() if output_dir else None

    ext_value = merged.get("ext") or ["md"]
    if isinstance(ext_value, str):
        extensions = [item.strip() for item in ext_value.split(",") if item.strip()]
    else:
        extensions = []
        for item in ext_value:  # type: ignore[assignment]
            if isinstance(item, str):
                extensions.extend([part.strip() for part in item.split(",") if part.strip()])
    if not extensions:
        extensions = ["md"]

    target_lang = (merged.get("target_lang") or merged.get("target-lang") or args.target_lang)
    if not target_lang:
        parser.error("--target-lang is required")

    source_lang = (merged.get("source_lang") or merged.get("source-lang") or args.source_lang or "auto")
    model = (
        merged.get("model")
        or os.environ.get("OPENROUTER_MODEL")
        or os.environ.get("MODEL")
        or DEFAULT_MODEL
    )

    concurrency = merged.get("concurrency")
    if concurrency is None:
        concurrency = min(8, max(2, os.cpu_count() or 4))
    concurrency = int(concurrency)

    include = _ensure_list(merged.get("include"))
    exclude = _ensure_list(merged.get("exclude"))

    chunk_config = merged.get("chunk") if isinstance(merged.get("chunk"), dict) else {}
    max_chars = int(
        merged.get("max_chars")
        or merged.get("max-chars")
        or (chunk_config or {}).get("max_chars")
        or (chunk_config or {}).get("max-chars")
        or DEFAULT_MAX_CHARS
    )
    split_threshold_value = (
        merged.get("split_threshold")
        or merged.get("split-threshold")
        or (chunk_config or {}).get("split_threshold")
        or (chunk_config or {}).get("split-threshold")
        or os.environ.get("TRANSFOLD_SPLIT_THRESHOLD")
    )
    split_threshold: Optional[int] = None
    if split_threshold_value not in (None, ""):
        try:
            split_threshold = int(split_threshold_value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            parser.error("split_threshold must be an integer")
        if split_threshold <= 0:
            parser.error("split_threshold must be a positive integer")
    chunk_strategy = (
        merged.get("chunk_strategy")
        or merged.get("chunk-strategy")
        or (chunk_config or {}).get("strategy")
        or "markdown"
    )

    translate_code = _resolve_bool(
        merged.get("translate_code"),
        merged.get("translate-code"),
        (chunk_config or {}).get("translate_code"),
        (chunk_config or {}).get("translate-code"),
        default=False,
    )
    translate_frontmatter = _resolve_bool(
        merged.get("translate_frontmatter"),
        merged.get("translate-frontmatter"),
        (chunk_config or {}).get("translate_frontmatter"),
        (chunk_config or {}).get("translate-frontmatter"),
        default=False,
    )

    stream_writes = _resolve_bool(
        merged.get("stream_writes"),
        merged.get("stream-writes"),
        default=False,
    )

    dry_run = bool(merged.get("dry_run") or merged.get("dry-run") or args.dry_run)
    backup = _resolve_bool(
        merged.get("backup"),
        merged.get("preserve_backup"),
        default=True,
    )
    backup = backup and not (
        merged.get("no_backup")
        or merged.get("no-backup")
        or args.no_backup
        or args.overwrite
    )

    retry = int(merged.get("retry") or DEFAULT_RETRY)
    timeout = float(merged.get("timeout") or DEFAULT_TIMEOUT)

    glossary_path = merged.get("glossary")
    glossary = Path(glossary_path).expanduser() if glossary_path else None

    batch_config = merged.get("batch") if isinstance(merged.get("batch"), dict) else {}
    batch_chars = int(
        merged.get("batch_chars")
        or merged.get("batch-chars")
        or (batch_config or {}).get("chars")
        or (batch_config or {}).get("max_chars")
        or DEFAULT_BATCH_CHARS
    )
    batch_segments = int(
        merged.get("batch_segments")
        or merged.get("batch-segments")
        or (batch_config or {}).get("segments")
        or (batch_config or {}).get("max_segments")
        or DEFAULT_BATCH_SEGMENTS
    )

    api_key = (
        merged.get("api_key")
        or merged.get("api-key")
        or args.api_key
        or os.environ.get("OPENROUTER_API_KEY")
    )
    if not api_key:
        parser.error("OpenRouter API key is required via --api-key or OPENROUTER_API_KEY")

    return Settings(
        input_dir=input_path,
        output_dir=output_path,
        extensions=extensions,
        target_lang=str(target_lang),
        source_lang=str(source_lang),
        model=str(model),
        concurrency=concurrency,
        include=include,
        exclude=exclude,
        max_chars=max_chars,
        split_threshold=split_threshold,
        chunk_strategy=str(chunk_strategy),
        translate_code=bool(translate_code),
        translate_frontmatter=bool(translate_frontmatter),
        dry_run=dry_run,
        backup=backup,
        stream_writes=bool(stream_writes),
        retry=retry,
        timeout=timeout,
        glossary=glossary,
        api_key=str(api_key),
        debug=bool(merged.get("debug") or args.debug),
        batch_chars=batch_chars,
        batch_segments=batch_segments,
    )


def _ensure_list(value: object) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        result: List[str] = []
        for item in value:
            if isinstance(item, str):
                result.extend([part.strip() for part in item.split(",") if part.strip()])
        return result
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def _resolve_bool(*values: object, default: bool = False) -> bool:
    for value in values:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.lower()
            if lowered in {"true", "1", "yes", "on"}:
                return True
            if lowered in {"false", "0", "no", "off"}:
                return False
    return default


def run(settings: Settings) -> int:
    start = time.time()
    if not settings.input_dir.is_dir():
        print(f"Input directory {settings.input_dir} does not exist", file=sys.stderr)
        return 1

    files = list(
        gather_files(
            settings.input_dir,
            extensions=settings.extensions,
            include=settings.include,
            exclude=settings.exclude,
        )
    )
    if not files:
        print("No files matched the provided criteria.")
        return 0

    errors: List[str] = []

    if settings.dry_run:
        total_segments = 0
        processed_files = 0
        for file_path in files:
            try:
                text = read_text(file_path)
            except Exception as exc:
                errors.append(f"{file_path}: {exc}")
                continue
            segmented = segment_document(
                text,
                strategy=settings.chunk_strategy,
                max_chars=settings.max_chars,
                preserve_code=not settings.translate_code,
                preserve_frontmatter=not settings.translate_frontmatter,
                split_threshold=settings.split_threshold,
            )
            translatable = sum(1 for seg in segmented.segments if seg.translate and seg.content.strip())
            total_segments += translatable
            processed_files += 1
            print(f"[DRY RUN] {file_path.relative_to(settings.input_dir)} -> {translatable} segments")
        print(f"Total files: {processed_files}, segments requiring translation: {total_segments}")
        if errors:
            print()
            print("Skipped files due to errors:")
            for item in errors:
                print(f" - {item}")
            return 1
        return 0

    glossary = None
    if settings.glossary:
        try:
            glossary = read_glossary(settings.glossary)
        except Exception as exc:
            errors.append(f"Failed to read glossary: {exc}")

    progress: Optional[tqdm] = None
    pending_progress = 0
    total_segments = 0
    documents_to_process = 0

    def on_progress(count: int) -> None:
        nonlocal pending_progress, progress
        if count <= 0:
            return
        if progress is None:
            pending_progress += count
        else:
            progress.update(count)

    async def on_retry(attempt: int, exc: Exception, delay: float) -> None:
        message = f"Retry attempt {attempt} after error: {exc}. Waiting {delay:.1f}s"
        if progress is not None:
            progress.write(message)
        else:
            print(message)

    try:
        translator = OpenRouterTranslator(
            api_key=settings.api_key,
            model=settings.model,
            target_lang=settings.target_lang,
            source_lang=settings.source_lang,
            timeout=settings.timeout,
            retry=settings.retry,
            concurrency=settings.concurrency,
            max_batch_chars=settings.batch_chars,
            max_batch_segments=settings.batch_segments,
            glossary=glossary,
            progress_callback=on_progress,
            retry_callback=on_retry,
            debug=settings.debug,
        )
    except Exception as exc:
        print(f"Failed to initialise translator: {exc}", file=sys.stderr)
        return 1

    writer = WriterThread()
    writer.start()

    async def process_document(
        file_path: Path,
        original: str,
        segmented: SegmentedDocument,
    ) -> None:
        destination = _resolve_output_path(settings, file_path)
        in_place = destination == file_path
        backup_required = settings.backup and in_place
        writes = 0
        next_emit_index = 0
        wrote_initial_chunk = False

        def _collect_ready_chunk() -> str:
            nonlocal next_emit_index
            ready: List[str] = []
            total = len(segmented.segments)
            while next_emit_index < total:
                seg = segmented.segments[next_emit_index]
                if seg.translate and seg.translation is None:
                    break
                ready.append(seg.output())
                next_emit_index += 1
            return "".join(ready)

        async def stream_segment(_segment) -> None:
            nonlocal writes, wrote_initial_chunk
            chunk = _collect_ready_chunk()
            if not chunk:
                return
            mode: WriteMode = "replace" if not wrote_initial_chunk else "append"
            writer.submit((destination, chunk, backup_required and not wrote_initial_chunk, mode))
            wrote_initial_chunk = True
            writes += 1

        segment_callback = stream_segment if settings.stream_writes else None

        try:
            await translator.translate_segments(
                segmented.segments,
                segment_callback=segment_callback,
            )
        except TranslationError as exc:
            errors.append(f"{file_path}: {exc}")
            if writes:
                writer.submit((destination, original, False, "replace"))
            return

        if writes == 0:
            rendered = segmented.merge()
            if destination != file_path or rendered != original:
                writer.submit((destination, rendered, backup_required, "replace"))

    queue: "asyncio.Queue[tuple[Path, str, SegmentedDocument] | None]" = asyncio.Queue(
        max(1, settings.concurrency * 2)
    )
    worker_count = max(1, settings.concurrency)

    async def producer() -> None:
        nonlocal documents_to_process, total_segments, progress, pending_progress
        for file_path in files:
            try:
                text, segmented, translatable = await read_and_segment_async(
                    file_path,
                    settings=settings,
                )
            except Exception as exc:
                errors.append(f"{file_path}: {exc}")
                continue
            total_segments += translatable
            documents_to_process += 1

            if progress is None and total_segments > 0:
                progress = tqdm(total=total_segments, unit="segment", desc="Translating")
                if pending_progress:
                    progress.update(pending_progress)
                    pending_progress = 0
            elif progress is not None:
                progress.total = total_segments
                progress.refresh()

            await queue.put((file_path, text, segmented))

        for _ in range(worker_count):
            await queue.put(None)

    async def worker() -> None:
        while True:
            item = await queue.get()
            if item is None:
                queue.task_done()
                break
            file_path, original, segmented = item
            try:
                await process_document(file_path, original, segmented)
            except Exception as exc:
                errors.append(f"{file_path}: {exc}")
            finally:
                queue.task_done()

    async def runner() -> None:
        producer_task = asyncio.create_task(producer())
        worker_tasks = [asyncio.create_task(worker()) for _ in range(worker_count)]
        try:
            await asyncio.gather(producer_task, *worker_tasks)
        finally:
            await translator.close()

    try:
        asyncio.run(runner())
    finally:
        writer.close()
        if progress is not None:
            progress.close()

    duration = time.time() - start
    print()
    print("Summary")
    print("=======")
    print(f"Files processed: {documents_to_process}")
    print(f"Segments translated: {translator.stats.total_segments}")
    print(f"API calls: {translator.stats.api_calls}")
    if translator.stats.batches:
        print(f"Batches submitted: {translator.stats.batches}")
    print(f"Retries performed: {translator.stats.retries}")
    if translator.stats.prompt_tokens or translator.stats.completion_tokens:
        print(
            "Token usage: prompt="
            f"{translator.stats.prompt_tokens}, completion={translator.stats.completion_tokens}"
        )
    print(f"Elapsed time: {duration:.2f}s")

    if errors:
        print()
        print("Failures:")
        for item in errors:
            print(f" - {item}")
        return 1
    return 0


def _resolve_output_path(settings: Settings, path: Path) -> Path:
    if settings.output_dir:
        rel = path.relative_to(settings.input_dir)
        return settings.output_dir / rel
    return path


def main(argv: Optional[List[str]] = None) -> int:
    settings = parse_arguments(argv)
    return run(settings)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
