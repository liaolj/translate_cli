from __future__ import annotations

from typing import Any

try:  # pragma: no cover - optional dependency handling
    from tqdm import tqdm as _tqdm  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - fallback

    class _TqdmFallback:
        def __init__(self, total: int | None = None, unit: str | None = None, desc: str | None = None, **_: Any) -> None:
            self.total = total
            self.unit = unit
            self.desc = desc

        def update(self, _n: int) -> None:
            return None

        def write(self, message: str) -> None:
            print(message)

        def close(self) -> None:
            return None

    def tqdm(*args: Any, **kwargs: Any) -> _TqdmFallback:
        return _TqdmFallback(*args, **kwargs)

else:  # pragma: no cover - thin wrapper

    def tqdm(*args: Any, **kwargs: Any):  # type: ignore[misc]
        return _tqdm(*args, **kwargs)
