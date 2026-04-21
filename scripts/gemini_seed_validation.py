#!/usr/bin/env python
"""Semantic validator for Ligilo 'Nivel Semilla' using Gemini 1.5 Flash."""

from __future__ import annotations

import argparse
import json
import os
from fastapi_app.services.gemini_seed_validator import DEFAULT_MODEL, validate_esperanto_content


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate Esperanto content with Gemini (Nivel Semilla)")
    parser.add_argument("text", help="Input text to validate")
    parser.add_argument("--api-key", default=os.getenv("GEMINI_API_KEY", ""), help="Gemini API key")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini model name")
    parser.add_argument("--max-retries", type=int, default=3, help="Retry attempts on API/JSON failures")
    parser.add_argument("--temperature", type=float, default=0.2, help="Gemini temperature")
    parser.add_argument("--timeout-seconds", type=int, default=60, help="HTTP timeout seconds")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()

    result = validate_esperanto_content(
        args.text,
        api_key=args.api_key,
        model=args.model,
        max_retries=args.max_retries,
        temperature=args.temperature,
        timeout_seconds=args.timeout_seconds,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
