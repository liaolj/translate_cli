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

## Development

Run the unit tests with:

```bash
python -m pytest
```

The tests include coverage for the `.env` loader and the HTTP client without performing
real network requests.
