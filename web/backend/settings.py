from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from transfold.config import load_config, load_env_file

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def _coerce_bool(*values: object, default: bool = False) -> bool:
    for value in values:
        if value is None:
            continue
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in _TRUE_VALUES:
                return True
            if lowered in _FALSE_VALUES:
                return False
    return default


def _coerce_int(value: object, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value: object, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class AppSettings:
    data_root: Path
    repos_root: Path
    outputs_root: Path
    logs_root: Path
    history_db: Path
    cache_db: Path
    target_lang: str
    source_lang: str
    model: str
    concurrency: int
    max_chars: int
    chunk_strategy: str
    split_threshold: Optional[int]
    translate_code: bool
    translate_frontmatter: bool
    retry: int
    timeout: float
    batch_chars: int
    batch_segments: int

    @classmethod
    def load(cls, *, env_path: Optional[Path] = None, config_path: Optional[str] = None) -> "AppSettings":
        load_env_file(env_path)

        config = load_config(config_path)

        data_root = Path(os.getenv("DATA_ROOT", "var/transfold")).expanduser().resolve()
        repos_root = data_root / "repos"
        outputs_root = data_root / "outputs"
        logs_root = data_root / "logs"
        history_db = data_root / "history.db"
        cache_db = data_root / "cache.db"

        target_lang = str(
            config.get("target_lang")
            or os.getenv("TRANSFOLD_TARGET_LANG")
            or os.getenv("TARGET_LANG")
            or "en"
        )
        source_lang = str(
            config.get("source_lang")
            or os.getenv("TRANSFOLD_SOURCE_LANG")
            or os.getenv("SOURCE_LANG")
            or "auto"
        )
        model = str(
            config.get("model")
            or os.getenv("OPENROUTER_MODEL")
            or os.getenv("MODEL")
            or "openrouter/auto"
        )

        concurrency = _coerce_int(
            config.get("concurrency")
            or os.getenv("TRANSFOLD_CONCURRENCY"),
            default=4,
        )
        chunk_config = config.get("chunk")
        chunk = chunk_config if isinstance(chunk_config, dict) else {}
        max_chars = _coerce_int(
            chunk.get("max_chars")
            or chunk.get("max-chars")
            or config.get("max_chars")
            or os.getenv("TRANSFOLD_MAX_CHARS"),
            default=4000,
        )
        chunk_strategy = str(
            chunk.get("strategy")
            or config.get("chunk_strategy")
            or config.get("chunk-strategy")
            or "markdown"
        )
        split_threshold_value = (
            chunk.get("split_threshold")
            or chunk.get("split-threshold")
            or config.get("split_threshold")
            or config.get("split-threshold")
            or os.getenv("TRANSFOLD_SPLIT_THRESHOLD")
        )
        split_threshold = None
        if split_threshold_value not in (None, ""):
            try:
                split_threshold = int(split_threshold_value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                split_threshold = None

        translate_code = _coerce_bool(
            config.get("translate_code"),
            chunk.get("translate_code"),
            os.getenv("TRANSFOLD_TRANSLATE_CODE"),
            default=False,
        )
        translate_frontmatter = _coerce_bool(
            config.get("translate_frontmatter"),
            chunk.get("translate_frontmatter"),
            os.getenv("TRANSFOLD_TRANSLATE_FRONTMATTER"),
            default=False,
        )

        retry = _coerce_int(config.get("retry") or os.getenv("TRANSFOLD_RETRY"), default=3)
        timeout = _coerce_float(config.get("timeout") or os.getenv("TRANSFOLD_TIMEOUT"), default=60.0)

        batch_config = config.get("batch")
        batch = batch_config if isinstance(batch_config, dict) else {}
        batch_chars = _coerce_int(
            batch.get("chars")
            or batch.get("max_chars")
            or os.getenv("TRANSFOLD_BATCH_CHARS"),
            default=16000,
        )
        batch_segments = _coerce_int(
            batch.get("segments")
            or batch.get("max_segments")
            or os.getenv("TRANSFOLD_BATCH_SEGMENTS"),
            default=6,
        )

        data_root.mkdir(parents=True, exist_ok=True)
        for path in (repos_root, outputs_root, logs_root):
            path.mkdir(parents=True, exist_ok=True)

        return cls(
            data_root=data_root,
            repos_root=repos_root,
            outputs_root=outputs_root,
            logs_root=logs_root,
            history_db=history_db,
            cache_db=cache_db,
            target_lang=target_lang,
            source_lang=source_lang,
            model=model,
            concurrency=concurrency,
            max_chars=max_chars,
            chunk_strategy=chunk_strategy,
            split_threshold=split_threshold,
            translate_code=translate_code,
            translate_frontmatter=translate_frontmatter,
            retry=retry,
            timeout=timeout,
            batch_chars=batch_chars,
            batch_segments=batch_segments,
        )


__all__ = ["AppSettings"]
