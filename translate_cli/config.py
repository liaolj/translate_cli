"""Configuration helpers for the OpenRouter integration."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Optional

_DEFAULT_ENV_PATH = Path(".env")


def load_env_file(path: Optional[Path] = None) -> None:
    """Load environment variables from a ``.env`` file if it exists.

    The implementation is intentionally tiny to avoid adding a runtime dependency
    on ``python-dotenv``. Only ``KEY=VALUE`` pairs are supported and existing
    environment variables are not overwritten.
    """

    env_path = path or _DEFAULT_ENV_PATH
    if isinstance(env_path, str):  # pragma: no cover - convenience for callers
        env_path = Path(env_path)

    if not env_path.exists():
        return

    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue

        # Do not override variables that are already set in the environment.
        if key in os.environ:
            continue

        normalized = value.strip()
        if normalized.startswith(("'", '"')) and normalized.endswith(("'", '"')) and len(normalized) >= 2:
            normalized = normalized[1:-1]

        os.environ[key] = normalized


@dataclass(frozen=True)
class OpenRouterConfig:
    """Runtime configuration for the OpenRouter client."""

    api_key: str
    model: str
    base_url: str = "https://openrouter.ai/api/v1"
    site_url: Optional[str] = None
    app_name: Optional[str] = None

    @classmethod
    def from_env(cls, *, env_path: Optional[Path] = None) -> "OpenRouterConfig":
        """Create a configuration object using environment variables.

        Parameters
        ----------
        env_path:
            Optional path to a ``.env`` file. When provided the file is loaded
            before reading values from the environment.
        """

        if env_path is not None:
            load_env_file(env_path)

        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY is not set. Create a .env file based on .env_example.")

        model = os.getenv("OPENROUTER_MODEL") or os.getenv("MODEL")
        if not model:
            raise ValueError("OPENROUTER_MODEL or MODEL must be set to choose the translation model.")

        base_url = os.getenv("OPENROUTER_BASE_URL", cls.base_url)
        site_url = os.getenv("OPENROUTER_SITE_URL")
        app_name = os.getenv("OPENROUTER_APP_NAME")
        return cls(
            api_key=api_key,
            model=model,
            base_url=base_url,
            site_url=site_url,
            app_name=app_name,
        )


__all__ = ["OpenRouterConfig", "load_env_file"]
