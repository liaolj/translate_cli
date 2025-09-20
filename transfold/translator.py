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

from .cache import TranslationCache
from .chunking import Segment


class TranslationError(RuntimeError):
    pass


@dataclass
class TranslatorStats:
    total_segments: int = 0
    cached_segments: int = 0
    api_calls: int = 0
    retries: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0


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
        cache: Optional[TranslationCache] = None,
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
        self.cache = cache
        self.glossary = glossary or {}
        self.progress_callback = progress_callback
        self.retry_callback = retry_callback
        self.system_prompt = system_prompt or self._default_system_prompt()
        self.debug = debug
        if httpx is None:
            raise RuntimeError(
                "httpx is required to use the OpenRouter translator. Install transfold with its dependencies."
            )
        self._client = httpx.AsyncClient(timeout=timeout)
        self._semaphore = asyncio.Semaphore(max(1, concurrency))
        self.stats = TranslatorStats()

    async def close(self) -> None:
        await self._client.aclose()

    async def translate_segments(
        self,
        segments: List[Segment],
        *,
        segment_callback: Optional[SegmentCallback] = None,
    ) -> None:
        pending: list[Awaitable[None]] = []

        for segment in segments:
            if not segment.translate or not segment.content.strip():
                segment.translation = segment.content
                if self.progress_callback:
                    self.progress_callback(1)
                pending.append(self._emit_segment(segment_callback, segment))
                continue

            self.stats.total_segments += 1
            chunk_hash = self.cache.compute_chunk_hash(segment.content) if self.cache else None
            cache_key = (
                self.cache.compute_cache_key(chunk_hash, self.target_lang, self.model)
                if self.cache and chunk_hash is not None
                else None
            )

            if cache_key and self.cache:
                cached = self.cache.get(cache_key)
                if cached is not None:
                    segment.translation = cached
                    self.stats.cached_segments += 1
                    if self.progress_callback:
                        self.progress_callback(1)
                    pending.append(self._emit_segment(segment_callback, segment))
                    continue

            pending.append(
                self._translate_segment(segment, chunk_hash, cache_key, segment_callback)
            )

        if not pending:
            return

        await asyncio.gather(*pending)

    async def _translate_segment(
        self,
        segment: Segment,
        chunk_hash: Optional[str],
        cache_key: Optional[str],
        segment_callback: Optional[SegmentCallback],
    ) -> None:
        last_error: Optional[Exception] = None
        for attempt in range(1, self.retry + 1):
            try:
                async with self._semaphore:
                    translation, usage = await self._request(segment.content)
                segment.translation = translation
                if cache_key and self.cache and chunk_hash:
                    self.cache.set(
                        cache_key,
                        chunk_hash=chunk_hash,
                        target_lang=self.target_lang,
                        model=self.model,
                        translation=translation,
                        metadata={"source_lang": self.source_lang},
                    )
                if usage:
                    self.stats.prompt_tokens += usage.get("prompt_tokens", 0)
                    self.stats.completion_tokens += usage.get("completion_tokens", 0)
                self.stats.api_calls += 1
                if self.progress_callback:
                    self.progress_callback(1)
                await self._emit_segment(segment_callback, segment)
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
        raise TranslationError(str(last_error) if last_error else "Unknown error")

    async def _request(self, text: str) -> tuple[str, Optional[dict]]:
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
            Do not add commentary or explanations; respond with the translated text only.{glossary_text}
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
