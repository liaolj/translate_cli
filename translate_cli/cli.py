"""Command line interface for the translate CLI."""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from .config import load_env_file
from .openrouter import OpenRouterClient, TranslationError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Translate text using OpenRouter.")
    parser.add_argument("text", help="Text to translate")
    parser.add_argument("target", help="Target language (name or ISO code)")
    parser.add_argument("source", nargs="?", default=None, help="Optional source language hint")
    parser.add_argument(
        "--env-file",
        default=None,
        help="Path to a .env file (defaults to .env in the current directory)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Request timeout in seconds (default: 60)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print OpenRouter request/response debug information",
    )
    return parser


def run(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        load_env_file(args.env_file)
        client = OpenRouterClient.from_env(
            env_path=args.env_file,
            timeout=args.timeout,
            debug=args.debug,
        )
    except ValueError as exc:
        parser.error(str(exc))

    try:
        translation = client.translate(args.text, args.target, source_language=args.source)
    except TranslationError as exc:
        parser.error(str(exc))

    print(translation)
    return 0


def main() -> None:
    sys.exit(run())


__all__ = ["main", "run", "build_parser"]
