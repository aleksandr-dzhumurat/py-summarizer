#!/usr/bin/env python3
"""
Generate LLM summary for an analyzed repository.

Reads the rendered prompt from .analysis/rendered_prompt.txt and calls the LLM,
printing the result to stdout.

Usage:
    python3 scripts/generate_llm_summary.py <repo_path>

Environment variables:
    DATA_DIR: Directory where repositories are located (required)
    ANTHROPIC_API_KEY: API key for the LLM (required)

Example:
    DATA_DIR=./data ANTHROPIC_API_KEY=sk-... python3 scripts/generate_llm_summary.py google/adk-python
"""

import os
import sys
from pathlib import Path

from src.llm.llm_adapter import summarize_with_llm


def main() -> int:
    if "DATA_DIR" not in os.environ:
        print("Error: DATA_DIR environment variable must be set", file=sys.stderr)
        return 1

    if len(sys.argv) < 2:
        print("Usage: python3 scripts/generate_llm_summary.py <repo_path>", file=sys.stderr)
        return 1

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable must be set", file=sys.stderr)
        return 1

    data_dir = Path(os.environ["DATA_DIR"])
    repo_path = data_dir / sys.argv[1]
    prompt_file = repo_path / ".analysis" / "rendered_prompt.txt"

    if not prompt_file.exists():
        print(f"Error: rendered prompt not found: {prompt_file}", file=sys.stderr)
        print("Run generate_code_graph.py first.", file=sys.stderr)
        return 1

    prompt = prompt_file.read_text(encoding="utf-8")
    result = summarize_with_llm(prompt, api_key)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
