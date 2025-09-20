from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

try:  # pragma: no cover - optional dependency
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover - Python <3.11 fallback
    tomllib = None  # type: ignore[assignment]

try:  # pragma: no cover - optional dependency
    import yaml  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    yaml = None  # type: ignore


DEFAULT_CONFIG_FILENAMES: tuple[str, ...] = (
    "transfold.config.yaml",
    "transfold.config.yml",
    "transfold.config.json",
    "transfold.config.toml",
)

_DEFAULT_ENV_PATH = Path(".env")


class ConfigError(RuntimeError):
    """Raised when a configuration file cannot be parsed."""


def _candidate_paths(explicit: Optional[str]) -> Iterable[Path]:
    if explicit:
        yield Path(explicit)
        return

    cwd = Path.cwd()
    for name in DEFAULT_CONFIG_FILENAMES:
        candidate = cwd / name
        if candidate.exists():
            yield candidate
            return


def load_config(path: Optional[str]) -> Dict[str, Any]:
    """Load configuration from a file if one exists.

    Parameters
    ----------
    path:
        The explicit path passed via CLI. When ``None`` the default file names are
        probed in the current working directory.
    """

    for candidate in _candidate_paths(path):
        if not candidate.exists():
            continue
        text = candidate.read_text(encoding="utf-8")
        suffix = candidate.suffix.lower()
        try:
            if suffix in {".yaml", ".yml"}:
                if yaml is None:
                    raise ConfigError(
                        "PyYAML is required to read YAML configuration files"
                    )
                data = yaml.safe_load(text) or {}
            elif suffix == ".json":
                data = json.loads(text or "{}")
            elif suffix == ".toml":
                if tomllib is None:
                    raise ConfigError(
                        "tomllib is unavailable; use Python 3.11+ for TOML configs"
                    )
                data = tomllib.loads(text or "")
            else:
                raise ConfigError(f"Unsupported config format: {candidate.suffix}")
        except (json.JSONDecodeError, ValueError) as exc:  # pragma: no cover - parse errors
            raise ConfigError(f"Failed to parse {candidate}: {exc}") from exc

        if not isinstance(data, dict):
            raise ConfigError("The configuration root must be a mapping/dictionary")

        return data
    return {}


def merge_config(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Merge two dictionaries recursively without mutating the inputs."""

    result: Dict[str, Any] = dict(base)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = merge_config(result[key], value)
        else:
            result[key] = value
    return result


def env_default(key: str, default: Optional[str] = None) -> Optional[str]:
    """Retrieve a configuration default from the environment."""

    return os.environ.get(key, default)


def load_env_file(path: Optional[Path | str] = None) -> None:
    """Load environment variables from a ``.env`` file without overriding existing values."""

    env_path: Path
    if path is None:
        env_path = _DEFAULT_ENV_PATH
    elif isinstance(path, Path):
        env_path = path
    else:
        env_path = Path(path)

    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue

        if key in os.environ:
            continue

        normalized = value.strip()
        if (
            len(normalized) >= 2
            and normalized[0] in {'"', "'"}
            and normalized[-1] == normalized[0]
        ):
            normalized = normalized[1:-1]

        os.environ[key] = normalized
