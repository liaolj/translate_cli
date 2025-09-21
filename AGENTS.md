# Repository Guidelines

## Project Structure & Module Organization
- `translate_cli/`: single-request CLI, `.env` loading, and OpenRouter client wrappers; use `config.py` for settings and `openrouter.py` for API calls.
- `transfold/`: batch translation engine with `cli.py`, `chunking.py`, `translator.py`, and `files.py`; async progress utilities live alongside.
- `tests/`: pytest suites mirroring modules; see `tests/test_openrouter_client.py` for HTTP stubbing patterns.
- Top-level assets (`pyproject.toml`, `.env_example`, `README.md`) define packaging, secrets, and onboarding.

## Build, Test, and Development Commands
- `python -m translate_cli "Hello" fr` — quick sanity check translating a literal string to French.
- `python -m transfold.cli --input docs --target-lang es --dry-run` — validate batch runs without invoking the API.
- `pip install -e .[yaml]` — install dependencies in editable mode with optional YAML parsing extras.
- `python -m pytest --maxfail=1 --ff` — run the test suite, prioritizing recent failures for faster feedback.

## Coding Style & Naming Conventions
- Target Python 3.10+, 4-space indentation, PEP 8, and snake_case files; prefer typed dataclasses for shared models.
- keep CLI parsers isolated in `build_parser` helpers; group imports stdlib > third-party > local and expose public APIs via `__all__`.
- Default to ASCII in source unless a module already relies on Unicode literals.

## Testing Guidelines
- Tests live under `tests/` with names like `test_translator.py`; extend existing fixtures (`DummyHTTPResponse`) and patch API calls via `unittest.mock.patch`.
- Cover new chunking/batching logic with async-aware tests; justify any coverage gaps in the PR description.
- Run `python -m pytest -k keyword` for focused debugging.

## Commit & Pull Request Guidelines
- Use imperative commit subjects (e.g., `Add OpenRouter-powered translation CLI`) and wrap bodies near 72 characters.
- Reference issues via `Fixes #123` or `Refs #123`; include CLI flag or config key changes in PR descriptions.
- Provide evidence of local testing (pytest output, CLI dry runs) and flag any manual verification steps for translator or batching changes.

## Security & Configuration Tips
- Copy `.env_example` to `.env`, populate `OPENROUTER_API_KEY`, `MODEL`, and optional proxies; never commit secrets.
- Prefer environment variables for credentials over CLI flags; avoid embedding API keys in code or fixtures.
