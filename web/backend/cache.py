from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class CacheKey:
    content_hash: str
    target_lang: str
    model: str
    source_lang: str


class TranslationCache:
    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._lock = threading.Lock()
        if not db_path.parent.exists():
            db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn, conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS translations (
                    content_hash TEXT NOT NULL,
                    target_lang TEXT NOT NULL,
                    source_lang TEXT NOT NULL,
                    model TEXT NOT NULL,
                    translated TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (content_hash, target_lang, source_lang, model)
                )
                """
            )

    def get(self, key: CacheKey) -> Optional[str]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT translated FROM translations
                WHERE content_hash = ?
                  AND target_lang = ?
                  AND source_lang = ?
                  AND model = ?
                """,
                (key.content_hash, key.target_lang, key.source_lang, key.model),
            ).fetchone()
        return row["translated"] if row else None

    def set(self, key: CacheKey, translated: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as conn, conn:
            conn.execute(
                """
                INSERT INTO translations (content_hash, target_lang, source_lang, model, translated, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(content_hash, target_lang, source_lang, model)
                DO UPDATE SET translated = excluded.translated, updated_at = excluded.updated_at
                """,
                (key.content_hash, key.target_lang, key.source_lang, key.model, translated, now),
            )


__all__ = ["TranslationCache", "CacheKey"]
