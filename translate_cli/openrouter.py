"""HTTP client for interacting with the OpenRouter API."""

from __future__ import annotations

import json
import textwrap
from typing import Dict, Iterable, List, Optional
from urllib import error, request

from .config import OpenRouterConfig

_CHAT_COMPLETIONS_PATH = "/chat/completions"


class TranslationError(RuntimeError):
    """Raised when the OpenRouter API returns an unexpected response."""


def _normalize_messages(content: str, *, source_language: Optional[str], target_language: str) -> List[Dict[str, str]]:
    system_prompt = (
        "You are a translation engine. Translate the user input into the requested "
        "language. Return only the translated text without additional commentary."
    )

    user_prompt_parts = []
    if source_language:
        user_prompt_parts.append(f"Source language: {source_language}.")
    user_prompt_parts.append(f"Target language: {target_language}.")
    user_prompt_parts.append("Text to translate:")
    user_prompt_parts.append(content)

    user_prompt = "\n".join(user_prompt_parts)

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


class OpenRouterClient:
    """Simple wrapper around the OpenRouter chat completions API."""

    def __init__(self, config: OpenRouterConfig, *, timeout: int = 60, debug: bool = False) -> None:
        self._config = config
        self._timeout = timeout
        self._debug = debug

    @classmethod
    def from_env(
        cls,
        *,
        env_path: Optional[str] = None,
        timeout: int = 60,
        debug: bool = False,
    ) -> "OpenRouterClient":
        config = OpenRouterConfig.from_env(env_path=env_path)
        return cls(config, timeout=timeout, debug=debug)

    # The return type is intentionally loose because downstream consumers may
    # choose to post-process the output.
    def translate(
        self,
        text: str,
        target_language: str,
        *,
        source_language: Optional[str] = None,
        extra_messages: Optional[Iterable[Dict[str, str]]] = None,
    ) -> str:
        """Translate ``text`` into ``target_language``.

        Parameters
        ----------
        text:
            The text to translate.
        target_language:
            Target language name or ISO code.
        source_language:
            Optional hint for the source language.
        extra_messages:
            Additional chat messages appended after the default system/user
            prompts. This is useful for experimentation and unit tests.
        """

        messages = _normalize_messages(text, source_language=source_language, target_language=target_language)
        if extra_messages:
            messages.extend(extra_messages)

        payload = {
            "model": self._config.model,
            "messages": messages,
        }

        if self._debug:
            preview = textwrap.shorten(text.replace("\n", " "), width=120, placeholder="...")
            print(
                f"[debug] OpenRouter request model={self._config.model} target={target_language}"
                f" chars={len(text)} preview='{preview}'"
            )

        response_json = self._post_json(payload)
        if self._debug and isinstance(response_json, dict):
            usage = response_json.get("usage") or {}
            print(f"[debug] OpenRouter response usage={usage}")
        try:
            choices = response_json["choices"]
            first_choice = choices[0]
            message = first_choice["message"]
            content = message["content"]
        except (KeyError, IndexError, TypeError) as exc:  # pragma: no cover - defensive, exercised in tests
            raise TranslationError("Unexpected OpenRouter response schema") from exc

        if isinstance(content, list):
            # Some models return a list of content chunks. Concatenate them for a
            # more convenient return value.
            text_chunks = [item.get("text", "") for item in content if isinstance(item, dict)]
            normalized = "".join(text_chunks).strip()
        else:
            normalized = str(content).strip()

        if not normalized:
            raise TranslationError("OpenRouter returned an empty translation")
        return normalized

    def _post_json(self, payload: Dict[str, object]) -> Dict[str, object]:
        url = self._config.base_url.rstrip("/") + _CHAT_COMPLETIONS_PATH
        body = json.dumps(payload).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._config.api_key}",
            "HTTP-Referer": self._config.site_url or "https://github.com/openrouter-ai/openrouter-python",  # official guidance
            "X-Title": self._config.app_name or "translate-cli",
        }

        req = request.Request(url, data=body, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=self._timeout) as resp:
                raw_body = resp.read()
        except error.HTTPError as exc:  # pragma: no cover - network errors are mocked in tests
            raise TranslationError(f"OpenRouter API returned HTTP {exc.code}") from exc
        except error.URLError as exc:  # pragma: no cover - network errors are mocked in tests
            raise TranslationError("Failed to connect to OpenRouter API") from exc

        try:
            parsed: Dict[str, object] = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise TranslationError("OpenRouter API returned invalid JSON") from exc

        return parsed


__all__ = ["OpenRouterClient", "TranslationError"]
