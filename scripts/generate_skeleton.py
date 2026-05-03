#!/usr/bin/env python3
"""Generate code skeleton for a GitHub repository.

Usage:
    python3 scripts/generate_skeleton.py <github_url>

Environment variables:
    DATA_DIR: Directory where repositories are cloned (required)
"""

import asyncio
import os
import sys

import tiktoken

from src.py_summarizer.naive_skeleton import skeleton_pipeline
from src.py_summarizer.utils import clone_repo, get_logger

logger = get_logger(__name__)


async def generate_skeleton(repo_url: str) -> int:
    """Clone repository (if needed) and generate code skeleton.

    Returns:
        0 on success, 1 on failure
    """
    print(f"Repository: {repo_url}")

    try:
        repo_path = await clone_repo(repo_url, timeout=180)
        print(f"Repository location: {repo_path}")
    except Exception as exc:
        logger.error(f"Failed to clone repository: {exc}")
        return 1

    skeleton_text = await skeleton_pipeline(repo_path)
    print(skeleton_text)
    lines = skeleton_text.splitlines()
    encoding = tiktoken.get_encoding("cl100k_base")
    token_count = len(encoding.encode(skeleton_text))
    print(f"  Total size: {len(skeleton_text):,} characters, {len(lines):,} lines, ~{token_count:,} tokens")


def main() -> int:
    if "DATA_DIR" not in os.environ:
        print("Error: DATA_DIR environment variable must be set", file=sys.stderr)
        print("Example: export DATA_DIR=/path/to/data", file=sys.stderr)
        return 1

    if len(sys.argv) < 2:
        raise RuntimeError(
            "Repository URL is required.\n"
            "Usage: python3 scripts/generate_skeleton.py <github_url>"
        )

    repo_url = sys.argv[1]

    if "github.com" not in repo_url:
        print(f"Error: Only GitHub URLs are supported (got: {repo_url})", file=sys.stderr)
        return 1

    return asyncio.run(generate_skeleton(repo_url))


if __name__ == "__main__":
    raise SystemExit(main())
