import asyncio
from types import SimpleNamespace

import pytest

from transfold.chunking import Segment
from transfold.translator import BatchSegmentMismatch, OpenRouterTranslator, TranslationError


class DummyAsyncClient:
    def __init__(self, *_, **__):
        return None

    async def post(self, *_, **__):  # pragma: no cover - network should not be used in tests
        raise AssertionError("HTTP requests are not expected in tests")

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_translator_enforces_pending_batch_limit(monkeypatch):
    httpx_stub = SimpleNamespace(AsyncClient=DummyAsyncClient, HTTPStatusError=RuntimeError)
    monkeypatch.setattr("transfold.translator.httpx", httpx_stub)

    event = asyncio.Event()
    call_started = 0

    async def fake_request_batch(self, batch):
        nonlocal call_started
        call_started += 1
        if call_started == 1:
            await event.wait()
        return [f"tx-{seg.index}" for seg in batch], {}

    monkeypatch.setattr(OpenRouterTranslator, "_request_batch", fake_request_batch)

    translator = OpenRouterTranslator(
        api_key="key",
        model="model",
        target_lang="fr",
        concurrency=2,
        max_batch_segments=1,
        max_pending_batches=1,
    )

    segments = [Segment(index=i, content=f"s{i}") for i in range(4)]

    async def run_translate():
        await translator.translate_segments(segments)

    task = asyncio.create_task(run_translate())
    await asyncio.sleep(0.05)
    assert call_started == 1
    event.set()
    await task
    assert call_started == len(segments)

    for segment in segments:
        assert segment.translation == f"tx-{segment.index}"

    await translator.close()


@pytest.mark.asyncio
async def test_parse_batch_response_handles_trailing_delimiter(monkeypatch):
    httpx_stub = SimpleNamespace(AsyncClient=DummyAsyncClient, HTTPStatusError=RuntimeError)
    monkeypatch.setattr("transfold.translator.httpx", httpx_stub)

    translator = OpenRouterTranslator(
        api_key="key",
        model="model",
        target_lang="fr",
    )

    delimiter = translator._batch_delimiter
    message = f"Bonjour{delimiter}Salut{delimiter}\n"

    translations = translator._parse_batch_response(message, 2)
    assert translations == ["Bonjour", "Salut"]

    await translator.close()


@pytest.mark.asyncio
async def test_translator_falls_back_to_single_on_mismatch(monkeypatch):
    httpx_stub = SimpleNamespace(AsyncClient=DummyAsyncClient, HTTPStatusError=RuntimeError)
    monkeypatch.setattr("transfold.translator.httpx", httpx_stub)

    translator = OpenRouterTranslator(
        api_key="key",
        model="model",
        target_lang="fr",
        max_batch_segments=4,
    )

    segments = [Segment(index=i, content=f"seg-{i}") for i in range(2)]

    async def fake_request_batch(self, batch):
        raise BatchSegmentMismatch(
            expected=len(batch),
            actual=1,
            raw="partial",
            usage={"prompt_tokens": 5, "completion_tokens": 7},
        )

    single_calls: list[str] = []

    async def fake_request_single(self, text):
        single_calls.append(text)
        return f"tx-{text}", {"prompt_tokens": 1, "completion_tokens": 2}

    monkeypatch.setattr(OpenRouterTranslator, "_request_batch", fake_request_batch)
    monkeypatch.setattr(OpenRouterTranslator, "_request_single", fake_request_single)

    await translator.translate_segments(segments)

    assert [segment.translation for segment in segments] == ["tx-seg-0", "tx-seg-1"]
    assert single_calls == ["seg-0", "seg-1"]
    assert translator.stats.api_calls == 1 + len(segments)
    assert translator.stats.batches == 1
    assert translator.stats.prompt_tokens == 5 + len(segments)
    assert translator.stats.completion_tokens == 7 + 2 * len(segments)

    await translator.close()


@pytest.mark.asyncio
async def test_translate_segments_times_out(monkeypatch):
    class SlowClient:
        def __init__(self, *_, **__):
            return None

        async def post(self, *_, **__):
            try:
                await asyncio.sleep(0.2)
            except asyncio.CancelledError:
                raise
            raise AssertionError("Request should have timed out before completing")

        async def aclose(self) -> None:
            return None

    httpx_stub = SimpleNamespace(AsyncClient=SlowClient, HTTPStatusError=RuntimeError)
    monkeypatch.setattr("transfold.translator.httpx", httpx_stub)

    translator = OpenRouterTranslator(
        api_key="key",
        model="model",
        target_lang="fr",
        timeout=0.05,
        retry=1,
    )

    segments = [Segment(index=0, content="hello", translate=True)]

    with pytest.raises(TranslationError, match="timeout"):
        await translator.translate_segments(segments)

    await translator.close()
