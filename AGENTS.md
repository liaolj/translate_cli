# Repository Guidelines

## Project Structure & Module Organization
- `translate_cli/`: single-shot CLI, env loading (`config.py`), and HTTP client wrappers (`openrouter.py`).
- `transfold/`: batch translation engine (`cli.py`, `chunking.py`, `translator.py`, `cache.py`) plus async progress utilities.
- `tests/`: pytest-driven suites mirroring modules; reuse the `DummyHTTPResponse` and `unittest.mock.patch` pattern for HTTP stubs.
- Top-level assets (`pyproject.toml`, `.env_example`, `README.md`) define packaging, secrets, and developer onboarding expectations.

## Build, Test, and Development Commands
- `python -m translate_cli "Hello" fr`: smoke-test the simple translator.
- `python -m transfold.cli --input docs --target-lang es --dry-run`: audit batch settings without API calls.
- `pip install -e .[yaml]`: editable install with optional YAML config parsing.
- `python -m pytest`: run unit tests; append `-k keyword` or `-x` for focused runs.
- `python -m pytest --maxfail=1 --ff`: prioritize recent failures during debugging loops.

## Coding Style & Naming Conventions
- Target Python 3.10+, PEP 8, and 4-space indentation; modules use snake_case filenames.
- Prefer typed dataclasses and pure helpers as in `transfold/translator.py`; keep side effects in CLI layers.
- Maintain explicit `__all__` lists for public modules and group imports by stdlib, third-party, then local.
- Keep CLI argument parsing in dedicated `build_parser` functions; reuse `pathlib.Path` for filesystem work.
- Store configuration defaults at module level; document new environment keys in `.env_example` and `README.md`.

## Testing Guidelines
- Name tests `test_*.py` and collect them under `tests/`; pytest will also run `unittest.TestCase` classes already present.
- Patch network calls with `unittest.mock.patch` as shown in `tests/test_openrouter_client.py` to keep tests offline.
- Cover new chunking, caching, or retry logic with async-aware tests or synchronous unit seams.
- When skipping coverage (e.g., optional dependencies), justify the gap in the pull request description.

## Commit & Pull Request Guidelines
- Use short, imperative commit subjects (e.g., `Add OpenRouter-powered translation CLI`) and wrap bodies at ~72 characters.
- Group related changes per commit; reference issues via `Fixes #123` or `Refs #123` where applicable.
- Pull requests should explain motivation, headline behavior changes, and list new CLI flags or config keys.
- Include evidence of local testing (`pytest`, CLI dry-run) and note any manual verification for translators or cache migrations.
- Update docs (`README.md`, examples, config samples) whenever user-facing behavior shifts.

## Environment & Secrets
- Copy `.env_example` to `.env` and fill in `OPENROUTER_API_KEY`, `MODEL`, and any proxy overrides before running CLIs.
- Keep secrets out of version control; rely on local `.env` files or CI-managed secrets.
- Prefer environment variables over CLI flags for credentials; never embed API keys in fixtures or samples.
