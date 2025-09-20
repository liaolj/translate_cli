from __future__ import annotations

import os
import shutil
import tempfile
from fnmatch import fnmatch
from pathlib import Path
from typing import Iterable, Iterator, Sequence


class FileReadError(RuntimeError):
    pass


def gather_files(
    root: Path,
    *,
    extensions: Sequence[str],
    include: Sequence[str] | None = None,
    exclude: Sequence[str] | None = None,
) -> Iterator[Path]:
    include_patterns = list(include or [])
    exclude_patterns = list(exclude or [])
    normalized_exts = {
        ext.lower().lstrip(".") for ext in extensions if ext
    } or set()

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if normalized_exts:
            suffix = path.suffix.lower().lstrip(".")
            if suffix not in normalized_exts:
                continue
        rel = path.relative_to(root).as_posix()
        if include_patterns and not any(fnmatch(rel, pattern) for pattern in include_patterns):
            continue
        if exclude_patterns and any(fnmatch(rel, pattern) for pattern in exclude_patterns):
            continue
        yield path


def read_text(path: Path) -> str:
    try:
        data = path.read_bytes()
    except OSError as exc:  # pragma: no cover - depends on filesystem
        raise FileReadError(f"Failed to read {path}: {exc}") from exc
    if b"\0" in data:
        raise FileReadError(f"{path} appears to be a binary file; skipping")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FileReadError(f"{path} is not valid UTF-8: {exc}") from exc


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def atomic_write(
    path: Path,
    content: str,
    *,
    backup: bool = False,
    encoding: str = "utf-8",
) -> None:
    ensure_parent(path)
    tmp_fd, tmp_path = tempfile.mkstemp(prefix=path.name, dir=path.parent)
    try:
        with os.fdopen(tmp_fd, "w", encoding=encoding, newline="") as handle:
            handle.write(content)
        if backup and path.exists():
            backup_path = path.with_suffix(path.suffix + ".bak")
            shutil.copy2(path, backup_path)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def read_glossary(path: Path) -> dict[str, str]:
    suffix = path.suffix.lower()
    if suffix in {".json"}:
        import json

        return json.loads(path.read_text(encoding="utf-8"))
    if suffix in {".csv"}:
        import csv

        mapping: dict[str, str] = {}
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            for row in reader:
                if len(row) >= 2:
                    mapping[row[0].strip()] = row[1].strip()
        return mapping
    raise ValueError(f"Unsupported glossary format: {path.suffix}")
