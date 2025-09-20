from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .cache import TranslationCache
from .chunking import segment_document
from .config import merge_config, load_config
from .files import atomic_write, gather_files, read_glossary, read_text
from .progress import tqdm
from .translator import OpenRouterTranslator, TranslationError


DEFAULT_MODEL = "openrouter/auto"
DEFAULT_MAX_CHARS = 4000
DEFAULT_TIMEOUT = 60.0
DEFAULT_RETRY = 3


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
    chunk_strategy: str
    translate_code: bool
    translate_frontmatter: bool
    dry_run: bool
    backup: bool
    retry: int
    timeout: float
    cache_dir: Path
    glossary: Optional[Path]
    api_key: str


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Transfold – translate Markdown at scale using OpenRouter")
    parser.add_argument("--config", help="Path to a configuration file", default=None)
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
    parser.add_argument("--cache-dir", help="Cache directory", default=None)
    parser.add_argument("--glossary", help="Glossary file (JSON or CSV)", default=None)
    parser.add_argument("--api-key", help="OpenRouter API key", default=None)
    return parser


def parse_arguments(argv: Optional[List[str]] = None) -> Settings:
    parser = build_parser()
    args = parser.parse_args(argv)

    config_data = load_config(args.config)
    explicit_false = {"translate_code", "translate_frontmatter"}
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
    model = merged.get("model") or DEFAULT_MODEL

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

    cache_dir = Path(merged.get("cache_dir") or merged.get("cache-dir") or ".transfold-cache").expanduser()

    glossary_path = merged.get("glossary")
    glossary = Path(glossary_path).expanduser() if glossary_path else None

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
        chunk_strategy=str(chunk_strategy),
        translate_code=bool(translate_code),
        translate_frontmatter=bool(translate_frontmatter),
        dry_run=dry_run,
        backup=backup,
        retry=retry,
        timeout=timeout,
        cache_dir=cache_dir,
        glossary=glossary,
        api_key=str(api_key),
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

    documents = []
    total_segments = 0
    errors: List[str] = []

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
        )
        translatable = sum(1 for seg in segmented.segments if seg.translate and seg.content.strip())
        total_segments += translatable
        documents.append((file_path, text, segmented))

    if settings.dry_run:
        for file_path, _, segmented in documents:
            translatable = sum(1 for seg in segmented.segments if seg.translate and seg.content.strip())
            print(f"[DRY RUN] {file_path.relative_to(settings.input_dir)} -> {translatable} segments")
        print(f"Total files: {len(documents)}, segments requiring translation: {total_segments}")
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

    cache = TranslationCache(settings.cache_dir)
    progress = (
        tqdm(total=total_segments, unit="segment", desc="Translating")
        if total_segments
        else None
    )

    def on_progress(count: int) -> None:
        if count and progress is not None:
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
            cache=cache,
            glossary=glossary,
            progress_callback=on_progress,
            retry_callback=on_retry,
        )
    except Exception as exc:
        if progress is not None:
            progress.close()
        cache.close()
        print(f"Failed to initialise translator: {exc}", file=sys.stderr)
        return 1

    async def process() -> None:
        for file_path, original, segmented in documents:
            try:
                await translator.translate_segments(segmented.segments)
            except TranslationError as exc:
                errors.append(f"{file_path}: {exc}")
                continue
            rendered = segmented.merge()
            destination = _resolve_output_path(settings, file_path)
            if destination == file_path:
                backup = settings.backup
            else:
                backup = False
            if rendered == original:
                continue
            atomic_write(destination, rendered, backup=backup)

    try:
        asyncio.run(process())
    finally:
        asyncio.run(translator.close())
        cache.close()
        if progress is not None:
            progress.close()

    duration = time.time() - start
    print()
    print("Summary")
    print("=======")
    print(f"Files processed: {len(documents)}")
    print(f"Segments translated: {translator.stats.total_segments}")
    print(f"Segments served from cache: {translator.stats.cached_segments}")
    print(f"API calls: {translator.stats.api_calls}")
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
