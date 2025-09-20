import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from translate_cli.config import OpenRouterConfig, load_env_file


class LoadEnvFileTests(unittest.TestCase):
    def test_loads_simple_key_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("FOO=bar\nEMPTY=\n# comment\n")

            with patch.dict(os.environ, {}, clear=True):
                load_env_file(env_path)
                self.assertEqual(os.environ["FOO"], "bar")
                self.assertEqual(os.environ["EMPTY"], "")

    def test_does_not_override_existing_variables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("FOO=from_file\n")

            with patch.dict(os.environ, {"FOO": "from_env"}, clear=True):
                load_env_file(env_path)
                self.assertEqual(os.environ["FOO"], "from_env")


class OpenRouterConfigTests(unittest.TestCase):
    def test_reads_configuration_from_environment(self) -> None:
        with patch.dict(
            os.environ,
            {"OPENROUTER_API_KEY": "abc123", "OPENROUTER_MODEL": "openrouter/test"},
            clear=True,
        ):
            config = OpenRouterConfig.from_env()
            self.assertEqual(config.api_key, "abc123")
            self.assertEqual(config.model, "openrouter/test")
            self.assertEqual(config.base_url, "https://openrouter.ai/api/v1")

    def test_model_falls_back_to_generic_name(self) -> None:
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "abc123", "MODEL": "anthropic/claude"}, clear=True):
            config = OpenRouterConfig.from_env()
            self.assertEqual(config.model, "anthropic/claude")

    def test_env_file_is_loaded_when_path_is_provided(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("OPENROUTER_API_KEY=from_file\nOPENROUTER_MODEL=openrouter/file-model\n")

            with patch.dict(os.environ, {}, clear=True):
                config = OpenRouterConfig.from_env(env_path=env_path)
                self.assertEqual(config.api_key, "from_file")
                self.assertEqual(config.model, "openrouter/file-model")

    def test_missing_api_key_raises_value_error(self) -> None:
        with patch.dict(os.environ, {"OPENROUTER_MODEL": "openrouter/test"}, clear=True):
            with self.assertRaises(ValueError):
                OpenRouterConfig.from_env()

    def test_missing_model_raises_value_error(self) -> None:
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "abc123"}, clear=True):
            with self.assertRaises(ValueError):
                OpenRouterConfig.from_env()


if __name__ == "__main__":
    unittest.main()
