from __future__ import annotations

import asyncio
import inspect
import random
import textwrap
from dataclasses import dataclass
from typing import Awaitable, Callable, List, Optional

try:  # pragma: no cover - optional dependency
    import httpx  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - provide friendly error later
    httpx = None  # type: ignore

from .chunking import Segment


class TranslationError(RuntimeError):
    pass


class BatchSegmentMismatch(TranslationError):
    def __init__(
        self,
        *,
        expected: int,
        actual: int,
        raw: str,
        usage: Optional[dict] = None,
    ) -> None:
        super().__init__("OpenRouter batch translation did not return the expected number of segments")
        self.expected = expected
        self.actual = actual
        self.raw = raw
        self.usage = usage


@dataclass
class TranslatorStats:
    total_segments: int = 0
    api_calls: int = 0
    retries: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    batches: int = 0


RetryCallback = Callable[[int, Exception, float], Awaitable[None]]
ProgressCallback = Callable[[int], None]
SegmentCallback = Callable[[Segment], Awaitable[None] | None]


class OpenRouterTranslator:
    endpoint = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        target_lang: str,
        source_lang: str = "auto",
        timeout: float = 60.0,
        retry: int = 3,
        concurrency: int = 4,
        max_batch_chars: int = 16000,
        max_batch_segments: int = 8,
        max_pending_batches: Optional[int] = None,
        glossary: Optional[dict[str, str]] = None,
        progress_callback: Optional[ProgressCallback] = None,
        retry_callback: Optional[RetryCallback] = None,
        system_prompt: Optional[str] = None,
        debug: bool = False,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.target_lang = target_lang
        self.source_lang = source_lang
        self.timeout = timeout
        self.retry = retry
        self.glossary = glossary or {}
        self.progress_callback = progress_callback
        self.retry_callback = retry_callback
        self._batch_delimiter = "<TRANSFOLD_SEGMENT_BREAK>"
        self.system_prompt = system_prompt or self._default_system_prompt()
        self.debug = debug
        self.max_batch_chars = max(1, max_batch_chars)
        self.max_batch_segments = max(1, max_batch_segments)
        pending_batches = max_pending_batches if max_pending_batches is not None else max(1, concurrency * 2)
        self.max_pending_batches = max(1, pending_batches)
        if httpx is None:
            raise RuntimeError(
                "httpx is required to use the OpenRouter translator. Install transfold with its dependencies."
            )
        self._client = httpx.AsyncClient(timeout=timeout)
        self._semaphore = asyncio.Semaphore(max(1, concurrency))
        self._pending_batches = asyncio.Semaphore(self.max_pending_batches)
        self.stats = TranslatorStats()

    async def close(self) -> None:
        await self._client.aclose()

    async def translate_segments(
        self,
        segments: List[Segment],
        *,
        segment_callback: Optional[SegmentCallback] = None,
    ) -> None:
        tasks: set[asyncio.Task[None]] = set()
        batch: list[Segment] = []
        batch_chars = 0

        async def schedule_batch(batch_copy: list[Segment]) -> None:
            await self._pending_batches.acquire()

            async def runner() -> None:
                try:
                    await self._translate_batch(batch_copy, segment_callback)
                finally:
                    self._pending_batches.release()

            task = asyncio.create_task(runner())
            tasks.add(task)

            def _cleanup(_t: asyncio.Task[None]) -> None:
                tasks.discard(_t)

            task.add_done_callback(_cleanup)

        async def flush_batch() -> None:
            nonlocal batch, batch_chars
            if not batch:
                return
            await schedule_batch(list(batch))
            batch = []
            batch_chars = 0

        for segment in segments:
            if not segment.translate or not segment.content.strip():
                segment.translation = segment.content
                if self.progress_callback:
                    self.progress_callback(1)
                emit_result = self._emit_segment(segment_callback, segment)
                if inspect.isawaitable(emit_result):
                    await emit_result
                continue

            self.stats.total_segments += 1
            content_length = len(segment.content)
            if (
                batch
                and (
                    len(batch) >= self.max_batch_segments
                    or batch_chars + content_length > self.max_batch_chars
                )
            ):
                await flush_batch()

            batch.append(segment)
            batch_chars += content_length

        await flush_batch()

        if not tasks:
            return

        await asyncio.gather(*tasks)

    async def _translate_batch(
        self,
        batch: List[Segment],
        segment_callback: Optional[SegmentCallback],
    ) -> None:
        last_error: Optional[Exception] = None
        for attempt in range(1, self.retry + 1):
            try:
                async with self._semaphore:
                    translations, usage = await self._request_batch(batch)
            except BatchSegmentMismatch as mismatch:
                if mismatch.usage:
                    self.stats.prompt_tokens += mismatch.usage.get("prompt_tokens", 0)
                    self.stats.completion_tokens += mismatch.usage.get("completion_tokens", 0)
                self.stats.api_calls += 1
                self.stats.batches += 1
                if self.debug:
                    preview = textwrap.shorten(
                        mismatch.raw.replace("\n", " "),
                        width=120,
                        placeholder="...",
                    )
                    print(
                        "[debug] OpenRouter batch mismatch expected="
                        f"{mismatch.expected} actual={mismatch.actual} preview='{preview}'"
                    )
                await self._translate_batch_individually(batch, segment_callback)
                return
            except Exception as exc:  # broad catch to honour retry semantics
                last_error = exc
                if attempt >= self.retry:
                    break
                self.stats.retries += 1
                delay = min(30.0, 2 ** (attempt - 1))
                # jitter between 0.1 and 0.5 seconds to avoid thundering herd
                jitter = random.uniform(0.1, 0.5)
                if self.retry_callback:
                    await self.retry_callback(attempt, exc, delay + jitter)
                await asyncio.sleep(delay + jitter)
            else:
                if len(translations) != len(batch):
                    raise TranslationError(
                        "OpenRouter returned a mismatched number of translations"
                    )
                if usage:
                    self.stats.prompt_tokens += usage.get("prompt_tokens", 0)
                    self.stats.completion_tokens += usage.get("completion_tokens", 0)
                self.stats.api_calls += 1
                self.stats.batches += 1
                if self.progress_callback:
                    self.progress_callback(len(batch))
                await asyncio.gather(
                    *[
                        self._apply_translation(segment_callback, segment, translation)
                        for segment, translation in zip(batch, translations)
                    ]
                )
                return
        raise TranslationError(str(last_error) if last_error else "Unknown error")

    async def _translate_batch_individually(
        self,
        batch: List[Segment],
        segment_callback: Optional[SegmentCallback],
    ) -> None:
        for segment in batch:
            async with self._semaphore:
                translation, usage = await self._request_single(segment.content)
            if usage:
                self.stats.prompt_tokens += usage.get("prompt_tokens", 0)
                self.stats.completion_tokens += usage.get("completion_tokens", 0)
            self.stats.api_calls += 1
            if self.progress_callback:
                self.progress_callback(1)
            await self._apply_translation(segment_callback, segment, translation)

    async def _apply_translation(
        self,
        segment_callback: Optional[SegmentCallback],
        segment: Segment,
        translation: str,
    ) -> None:
        segment.translation = translation
        await self._emit_segment(segment_callback, segment)

    async def _request_batch(self, batch: List[Segment]) -> tuple[List[str], Optional[dict]]:
        if len(batch) == 1:
            translation, usage = await self._request_single(batch[0].content)
            return [translation], usage

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": self._batch_prompt(batch)},
            ],
        }
        if self.debug:
            preview = textwrap.shorten(
                " ".join(seg.content.replace("\n", " ") for seg in batch),
                width=120,
                placeholder="...",
            )
            print(
                f"[debug] OpenRouter batch request model={self.model} segments={len(batch)} chars={sum(len(seg.content) for seg in batch)} preview='{preview}'"
            )
        response = await self._client.post(self.endpoint, json=payload, headers=headers)
        if self.debug:
            print(
                f"[debug] OpenRouter response status={response.status_code} request_id={response.headers.get('X-Request-Id', 'n/a')}"
            )
        if response.status_code >= 500 or response.status_code == 429:
            raise httpx.HTTPStatusError(
                f"Server error: {response.status_code} {response.text}", request=response.request, response=response
            )
        if response.status_code != 200:
            raise TranslationError(
                f"OpenRouter API returned status {response.status_code}: {response.text}"
            )
        data = response.json()
        usage = data.get("usage") if isinstance(data, dict) else None
        if self.debug and usage is not None:
            print(f"[debug] OpenRouter usage={usage}")
        try:
            message = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:  # pragma: no cover - depends on API
            raise TranslationError("Unexpected response format from OpenRouter API") from exc
        try:
            translations = self._parse_batch_response(message, len(batch))
        except BatchSegmentMismatch as mismatch:
            mismatch.usage = usage
            raise
        if self.debug:
            preview = textwrap.shorten(
                " ".join(t.replace("\n", " ") for t in translations),
                width=120,
                placeholder="...",
            )
            print(f"[debug] OpenRouter batch translation preview='{preview}'")
        return translations, usage

    async def _request_single(self, text: str) -> tuple[str, Optional[dict]]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": self._user_prompt(text)},
            ],
        }
        if self.debug:
            preview = textwrap.shorten(text.replace("\n", " "), width=120, placeholder="...")
            print(
                f"[debug] OpenRouter request model={self.model} target={self.target_lang} chars={len(text)} preview='{preview}'"
            )
        response = await self._client.post(self.endpoint, json=payload, headers=headers)
        if self.debug:
            print(
                f"[debug] OpenRouter response status={response.status_code} request_id={response.headers.get('X-Request-Id', 'n/a')}"
            )
        if response.status_code >= 500 or response.status_code == 429:
            raise httpx.HTTPStatusError(
                f"Server error: {response.status_code} {response.text}", request=response.request, response=response
            )
        if response.status_code != 200:
            raise TranslationError(
                f"OpenRouter API returned status {response.status_code}: {response.text}"
            )
        data = response.json()
        if self.debug and isinstance(data, dict):
            usage = data.get("usage") or {}
            print(f"[debug] OpenRouter usage={usage}")
        try:
            message = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:  # pragma: no cover - depends on API
            raise TranslationError("Unexpected response format from OpenRouter API") from exc
        translation = self._normalize_content(message)
        if not translation.strip():
            raise TranslationError("OpenRouter returned an empty translation")
        if self.debug:
            preview = textwrap.shorten(translation.replace("\n", " "), width=120, placeholder="...")
            print(f"[debug] OpenRouter translation preview='{preview}'")
        usage = data.get("usage") if isinstance(data, dict) else None
        return translation, usage

    def _batch_prompt(self, batch: List[Segment]) -> str:
        source_line = (
            f"The source language is {self.source_lang}."
            if self.source_lang != "auto"
            else "Detect the source language automatically."
        )
        parts = [
            source_line,
            f"The target language is {self.target_lang}.",
            "Translate each segment independently while preserving Markdown structure.",
            f"Return the translations in order, separated by the literal delimiter '{self._batch_delimiter}' with no extra text before the first translation or after the last translation.",
            "Segments:",
        ]
        for idx, segment in enumerate(batch, start=1):
            parts.append(f"Segment {idx} start")
            parts.append("---")
            parts.append(segment.content)
            parts.append("---")
            parts.append(f"Segment {idx} end")
        return "\n".join(parts)

    def _parse_batch_response(self, message: object, expected: int) -> List[str]:
        text = self._normalize_content(message)
        parts = text.split(self._batch_delimiter)
        results: List[str] = []
        for item in parts:
            candidate = item.strip("\n")
            if candidate.strip():
                results.append(candidate)
        if len(results) != expected:
            raise BatchSegmentMismatch(
                expected=expected,
                actual=len(results),
                raw=text,
            )
        return results

    def _normalize_content(self, message: object) -> str:
        if isinstance(message, list):
            parts: List[str] = []
            for item in message:
                if isinstance(item, dict):
                    parts.append(str(item.get("text", "")))
                else:
                    parts.append(str(item))
            return "".join(parts)
        return str(message)

    async def _emit_segment(
        self,
        callback: Optional[SegmentCallback],
        segment: Segment,
    ) -> None:
        if callback is None:
            return
        result = callback(segment)
        if inspect.isawaitable(result):
            await result

    def _default_system_prompt(self) -> str:
        glossary_text = ""
        if self.glossary:
            items = "\n".join(f"- {src} -> {dst}" for src, dst in self.glossary.items())
            glossary_text = "\nGlossary (use these translations verbatim):\n" + items
        return textwrap.dedent(
            f"""
            You are a professional technical documentation translator.
            Translate all provided text into {self.target_lang} while preserving Markdown structure and formatting.
            Do not translate fenced code blocks, inline code spans, URLs, or image paths.
            Do not add commentary or explanations; respond with the translated text only. When multiple segments are provided, return translations separated by the literal delimiter '{self._batch_delimiter}'.{glossary_text}
            """
        ).strip()

    def _user_prompt(self, text: str) -> str:
        source_line = (
            f"The source language is {self.source_lang}." if self.source_lang != "auto" else "Detect the source language automatically."
        )
        return textwrap.dedent(
            f"""
            {source_line}
            The target language is {self.target_lang}.
            Translate the following content. Return only the translated text without wrapping quotes.
            ---
            {text}
            ---
            """
        ).strip()
