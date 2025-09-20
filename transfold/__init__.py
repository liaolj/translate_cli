"""Transfold – translate Markdown trees with OpenRouter."""

from __future__ import annotations

__all__ = ["main", "__version__"]

__version__ = "0.1.0"

from .cli import main  # noqa: E402  (re-export for convenience)
