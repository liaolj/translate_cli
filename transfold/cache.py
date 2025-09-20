from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Optional


class TranslationCache:
    """A lightweight SQLite-backed cache for translated segments."""

    def __init__(self, cache_dir: Path) -> None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.path = cache_dir / "segments.sqlite3"
        self._conn = sqlite3.connect(self.path)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS translations (
                cache_key TEXT PRIMARY KEY,
                chunk_hash TEXT NOT NULL,
                target_lang TEXT NOT NULL,
                model TEXT NOT NULL,
                translation TEXT NOT NULL,
                metadata TEXT
            )
            """
        )
        self._conn.commit()
        self._lock = threading.Lock()
        self._pending_writes = 0
        self._commit_interval = 32

    def close(self) -> None:
        with self._lock:
            if self._pending_writes:
                self._conn.commit()
                self._pending_writes = 0
            self._conn.close()

    def flush(self) -> None:
        with self._lock:
            if not self._pending_writes:
                return
            self._conn.commit()
            self._pending_writes = 0

    def compute_chunk_hash(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def compute_cache_key(self, chunk_hash: str, target_lang: str, model: str) -> str:
        base = f"{chunk_hash}:{target_lang}:{model}"
        return hashlib.sha256(base.encode("utf-8")).hexdigest()

    def get(
        self, cache_key: str
    ) -> Optional[str]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT translation FROM translations WHERE cache_key = ?", (cache_key,)
            )
            row = cur.fetchone()
            return row[0] if row else None

    def set(
        self,
        cache_key: str,
        *,
        chunk_hash: str,
        target_lang: str,
        model: str,
        translation: str,
        metadata: Optional[dict] = None,
    ) -> None:
        payload = json.dumps(metadata or {}) if metadata else None
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO translations
                    (cache_key, chunk_hash, target_lang, model, translation, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (cache_key, chunk_hash, target_lang, model, translation, payload),
            )
            self._pending_writes += 1
            if self._pending_writes >= self._commit_interval:
                self._conn.commit()
                self._pending_writes = 0
