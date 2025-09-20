import json
import unittest
from unittest.mock import patch

from translate_cli.config import OpenRouterConfig
from translate_cli.openrouter import OpenRouterClient, TranslationError


class DummyHTTPResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self) -> "DummyHTTPResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class OpenRouterClientTests(unittest.TestCase):
    def _make_client(self) -> OpenRouterClient:
        config = OpenRouterConfig(
            api_key="test_key",
            model="test-model",
            base_url="https://openrouter.ai/api/v1",
            site_url="https://example.com",
            app_name="translate-cli-tests",
        )
        return OpenRouterClient(config, timeout=5)

    def test_translate_parses_string_content(self) -> None:
        client = self._make_client()
        response_payload = {"choices": [{"message": {"content": "Bonjour"}}]}

        def fake_urlopen(req, timeout=0):
            self.assertEqual(req.get_full_url(), "https://openrouter.ai/api/v1/chat/completions")
            body = json.loads(req.data.decode("utf-8"))
            self.assertEqual(body["model"], "test-model")
            self.assertEqual(body["messages"][1]["role"], "user")
            self.assertIn("Target language", body["messages"][1]["content"])
            headers = {key.lower(): value for key, value in req.header_items()}
            self.assertEqual(headers["authorization"], "Bearer test_key")
            self.assertEqual(headers["x-title"], "translate-cli-tests")
            return DummyHTTPResponse(response_payload)

        with patch("translate_cli.openrouter.request.urlopen", side_effect=fake_urlopen):
            translated = client.translate("Hello", "French")
            self.assertEqual(translated, "Bonjour")

    def test_translate_concatenates_chunked_content(self) -> None:
        client = self._make_client()
        response_payload = {
            "choices": [
                {
                    "message": {
                        "content": [
                            {"text": "Par"},
                            {"text": "ble"},
                        ]
                    }
                }
            ]
        }

        with patch("translate_cli.openrouter.request.urlopen", return_value=DummyHTTPResponse(response_payload)):
            translated = client.translate("Blue", "French")
            self.assertEqual(translated, "Parble")

    def test_translate_raises_on_invalid_json(self) -> None:
        client = self._make_client()

        class InvalidResponse(DummyHTTPResponse):
            def read(self) -> bytes:  # type: ignore[override]
                return b"not json"

        with patch("translate_cli.openrouter.request.urlopen", return_value=InvalidResponse({})):
            with self.assertRaises(TranslationError):
                client.translate("Hello", "French")


if __name__ == "__main__":
    unittest.main()
