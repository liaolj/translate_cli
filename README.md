
# translate_cli

A lightweight command line interface that translates text using the [OpenRouter](https://openrouter.ai) API.

## Quick start

1. Copy `.env_example` to `.env` and fill in your credentials:

   ```bash
   cp .env_example .env
   # then edit .env to set OPENROUTER_API_KEY and MODEL
   ```

2. Create a virtual environment and install the requirements if needed (no third-party
   dependencies are required for the core functionality).

3. Run the CLI:

   ```bash
   python -m translate_cli "Hello world" French
   ```

   Use `python -m translate_cli --help` to view all available options.

## Environment variables

The application relies on the following variables, which can be stored in a `.env` file:

- `OPENROUTER_API_KEY` – required API key generated from the OpenRouter dashboard.
- `MODEL` (or `OPENROUTER_MODEL`) – required model identifier such as `openrouter/auto` or
  `openai/gpt-4o-mini`.
- `OPENROUTER_BASE_URL` – optional override when using a proxy instance.
- `OPENROUTER_SITE_URL` and `OPENROUTER_APP_NAME` – optional metadata forwarded to OpenRouter.
- `TRANSFOLD_SPLIT_THRESHOLD` – optional integer that keeps each Transfold file as a single translation when its character count stays at or below the threshold.

## Development

Run the unit tests with:

```bash
python -m pytest
```

The tests include coverage for the `.env` loader and the HTTP client without performing
real network requests.

# Transfold

Transfold is a command-line utility that recursively scans a directory tree, translates Markdown (or other text-based) files via the OpenRouter API, and writes the results back in-place or to a mirror output directory. The tool is designed for technical documentation workflows and keeps fenced code blocks, inline code and YAML front matter intact by default.

## Features

- Recursive discovery of files with configurable extensions, include and exclude patterns.
- Chunk-aware translation pipeline that respects Markdown structure and API character limits.
- Concurrent OpenRouter requests with exponential backoff and retry handling.
- Atomic file writes with optional `.bak` backups when overwriting source files.
- Batched requests that translate multiple segments per OpenRouter call, reducing latency at scale.
- Optional glossary ingestion (JSON or CSV) to enforce domain terminology.
- Dry-run mode for auditing which files and segments would be processed.
- Configurable via CLI flags or a `transfold.config.{yaml,json,toml}` file.

## Installation

The project ships with a `pyproject.toml`. Install the CLI (and optional YAML support) with:

```bash
pip install .
# or, for YAML configuration support
pip install .[yaml]
```

Alternatively, run the module directly without installation:

```bash
python -m transfold.cli --help
```

## Usage

```bash
transfold \
  --input ./docs \
  --target-lang zh \
  --ext md,txt \
  --output ./docs_zh \
  --concurrency 8
```

Key arguments:

| Flag | Description |
| ---- | ----------- |
| `--input` | **Required.** Root directory to scan for files. |
| `--target-lang` | **Required.** Output language code (e.g. `zh`, `en`). |
| `--ext` | Comma-separated list of extensions (default `md`). |
| `--output` | Optional output directory. If omitted, files are updated in place with `.bak` backups. |
| `--source-lang` | Source language code or `auto` (default). |
| `--model` | OpenRouter model identifier (default `openrouter/auto`). |
| `--concurrency` | Number of in-flight OpenRouter requests (default derived from CPU count). |
| `--max-chars` | Maximum characters per chunk before secondary splitting (default `4000`). Set `TRANSFOLD_SPLIT_THRESHOLD` in `.env` to keep smaller files as a single translation request. |
| `--translate-code` / `--no-translate-code` | Toggle translating fenced code blocks (default disabled). |
| `--translate-frontmatter` / `--no-translate-frontmatter` | Toggle translating YAML front matter (default disabled). |
| `--dry-run` | Report files and segment counts without contacting the API. |
| `--stream-writes` / `--no-stream-writes` | Opt-in partial writes after each translated segment (default disabled; buffers until document completion for best performance). |
| `--glossary` | Path to JSON or CSV glossary mapping source terms to fixed translations. |
| `--batch-chars` | Maximum characters combined into a single API request (default `16000`). |
| `--batch-segments` | Maximum segments grouped per request (default `6`). |
| `--retry`, `--timeout` | Control retry attempts and per-request timeout. |

Set the OpenRouter API key via the `OPENROUTER_API_KEY` environment variable (recommended) or pass `--api-key`. The key is never persisted to disk.

### Include/Exclude Patterns

Use `--include` / `--exclude` (repeatable) for glob-style pattern filtering relative to the input directory. For example:

```bash
transfold --input docs --target-lang zh --include "**/*.md" --exclude "**/node_modules/**"
```

### Dry Run

`--dry-run` prints all candidate files and the number of translation segments without performing any API calls. This is useful for estimating workload or verifying pattern filters.

### Glossary Support

Provide a JSON object (`{"source": "translation"}`) or two-column CSV file to pin terminology. Glossary entries are appended to the system prompt for every translation request.

## Configuration File

Transfold automatically loads configuration from `transfold.config.yaml`, `.yml`, `.json` or `.toml` in the current working directory. CLI flags override config values.

Example `transfold.config.yaml`:

```yaml
input: ./docs
output: ./docs_zh
ext: [md]
target_lang: zh
source_lang: auto
model: openrouter/auto
concurrency: 8
include:
  - "**/*.md"
exclude:
  - "**/node_modules/**"
chunk:
  strategy: markdown
  max_chars: 4000
  split_threshold: 8000
preserve_code: true
preserve_frontmatter: true
retry: 3
timeout: 60
backup: true

batch:
  chars: 16000
  segments: 6
```

## Logging & Output

During execution, Transfold displays a progress bar for translation segments, retry notifications, and a final summary with counts and (when provided by the API) token usage statistics. Failed files are listed at the end with their corresponding errors.

## Development

- Format and type-check using your preferred tools (no specific formatter enforced).
- Run the CLI locally with `python -m transfold.cli --help`.
- Contributions are welcome via pull requests.

## License

Distributed under the MIT License. See `LICENSE` for details.
