from __future__ import annotations

import asyncio
import inspect

import pytest


def pytest_configure(config: pytest.Config) -> None:  # pragma: no cover - pytest integration
    config.addinivalue_line("markers", "asyncio: run the marked test as an asyncio coroutine")


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> bool | None:  # pragma: no cover - pytest integration
    test_obj = pyfuncitem.obj
    if not inspect.iscoroutinefunction(test_obj):
        return None
    if pyfuncitem.get_closest_marker("asyncio") is None:
        return None

    funcargs = {
        name: pyfuncitem.funcargs[name]
        for name in pyfuncitem._fixtureinfo.argnames  # type: ignore[attr-defined]
        if name in pyfuncitem.funcargs
    }
    asyncio.run(test_obj(**funcargs))
    return True
