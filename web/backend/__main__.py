"""Convenience entry point for running the FastAPI backend in development.

The stock ``uvicorn`` command watches the entire project tree when ``--reload``
is enabled.  Our translation jobs clone Git repositories and persist outputs
under ``DATA_ROOT`` (defaults to ``var/transfold``), which can easily contain
thousands of files.  Watching those directories exhausts the inotify limit on
Linux and crashes the dev server.

This module wraps :func:`uvicorn.run` so we can opt in to autoreload while only
tracking the backend source directory.  We also explicitly exclude the data
directories derived from :class:`~web.backend.settings.AppSettings`, avoiding
the file-watch explosion that previously occurred.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, List, Sequence

import uvicorn

from .settings import AppSettings


def _to_unique_strings(paths: Iterable[Path]) -> List[str]:
    """Return a list of unique, resolved string paths."""

    unique: List[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved not in unique:
            unique.append(resolved)
    return [str(item) for item in unique]


def _should_reload(flag: str | None) -> bool:
    if flag is None:
        return True
    lowered = flag.strip().lower()
    return lowered not in {"0", "false", "no", "off"}


def main() -> None:
    """Start the FastAPI application with sensible dev defaults."""

    settings = AppSettings.load()

    backend_dir = Path(__file__).resolve().parent
    reload_dirs: Sequence[Path] = (backend_dir,)

    # Ignore dynamically populated directories that can contain thousands of
    # files (cloned repos, translation outputs, logs, databases...).
    reload_excludes: Sequence[Path] = (
        settings.data_root,
        settings.repos_root,
        settings.outputs_root,
        settings.logs_root,
        settings.history_db.parent,
        settings.cache_db.parent,
    )

    uvicorn.run(  # pragma: no cover - thin wrapper around uvicorn
        "web.backend.app:app",
        host=os.getenv("UVICORN_HOST", "127.0.0.1"),
        port=int(os.getenv("UVICORN_PORT", "8000")),
        reload=_should_reload(os.getenv("UVICORN_RELOAD")),
        reload_dirs=_to_unique_strings(reload_dirs),
        reload_excludes=_to_unique_strings(reload_excludes),
    )


if __name__ == "__main__":
    main()

