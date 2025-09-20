# Transfold

Transfold is a command-line utility that recursively scans a directory tree, translates Markdown (or other text-based) files via the OpenRouter API, and writes the results back in-place or to a mirror output directory. The tool is designed for technical documentation workflows and keeps fenced code blocks, inline code and YAML front matter intact by default.

## Features

- Recursive discovery of files with configurable extensions, include and exclude patterns.
- Chunk-aware translation pipeline that respects Markdown structure and API character limits.
- Concurrent OpenRouter requests with exponential backoff and retry handling.
- Atomic file writes with optional `.bak` backups when overwriting source files.
- Persistent SQLite cache to avoid re-translating unchanged segments.
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
| `--max-chars` | Maximum characters per chunk before secondary splitting (default `4000`). |
| `--translate-code` / `--no-translate-code` | Toggle translating fenced code blocks (default disabled). |
| `--translate-frontmatter` / `--no-translate-frontmatter` | Toggle translating YAML front matter (default disabled). |
| `--dry-run` | Report files and segment counts without contacting the API. |
| `--cache-dir` | Override the cache directory (default `.transfold-cache`). |
| `--glossary` | Path to JSON or CSV glossary mapping source terms to fixed translations. |
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
preserve_code: true
preserve_frontmatter: true
retry: 3
timeout: 60
cache_dir: ./.transfold-cache
backup: true
```

## Cache

The cache lives in `.transfold-cache/segments.sqlite3` by default and stores per-chunk translations keyed by source content, target language and model. Delete the file to force re-translation.

## Logging & Output

During execution, Transfold displays a progress bar for translation segments, retry notifications, and a final summary with counts and (when provided by the API) token usage statistics. Failed files are listed at the end with their corresponding errors.

## Development

- Format and type-check using your preferred tools (no specific formatter enforced).
- Run the CLI locally with `python -m transfold.cli --help`.
- Contributions are welcome via pull requests.

## License

Distributed under the MIT License. See `LICENSE` for details.
