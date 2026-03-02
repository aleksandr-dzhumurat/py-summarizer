#!/usr/bin/env python3
"""Generate code skeleton for a GitHub repository.

This script:
1. Clones the repository (if not already present)
2. Indexes all files in the repository
3. Generates a code skeleton (SKELETON.txt)

The skeleton includes imports and function signatures from Python files,
which can be used for analysis or as input to LLM summarization.

Usage:
    python3 scripts/generate_skeleton.py [repo_url]
    
Environment variables:
    DATA_DIR: Directory where repositories are cloned (required)
    REPO: Default repository URL if not provided as argument
"""

import asyncio
import os
import sys

import tiktoken

from src.naive_skeleton import code_skeleton
from src.utils import clone_repo, get_index, get_logger

logger = get_logger(__name__)


async def generate_skeleton(repo_url: str) -> int:
    """Clone repository (if needed) and generate code skeleton.
    
    Args:
        repo_url: GitHub repository URL to process
        
    Returns:
        0 on success, 1 on failure
    """
    print(f"Repository: {repo_url}")
    
    # Step 1: Clone repository (or use existing clone)
    try:
        repo_path = await clone_repo(repo_url, timeout=180)
        print(f"Repository location: {repo_path}")
    except Exception as exc:
        logger.error(f"Failed to clone repository: {exc}")
        return 1
    
    # Step 2: Index repository files
    try:
        indexed = get_index(str(repo_path))
        print(f"✓ Indexed {len(indexed)} files")
        
        if not indexed:
            print("⚠ No files to process")
            return 1
            
    except Exception as e:
        logger.error(f"Indexing failed: {e}")
        return 1
    
    # Step 3: Generate code skeleton
    try:
        skeleton_text = code_skeleton(indexed, root_dir=str(repo_path))
        lines = skeleton_text.splitlines()
        
        # Save skeleton to file
        analysis_dir = repo_path / ".analysis"
        analysis_dir.mkdir(exist_ok=True)
        skeleton_file = analysis_dir / "skeleton.txt"
        skeleton_file.write_text(skeleton_text, encoding="utf-8")
        print(f"\n✓ Skeleton saved to: {skeleton_file}")
        
        # Calculate token count
        encoding = tiktoken.get_encoding("cl100k_base")
        token_count = len(encoding.encode(skeleton_text))
        
        print(f"  Total size: {len(skeleton_text):,} characters, {len(lines):,} lines, ~{token_count:,} tokens")
        
    except Exception as e:
        logger.error(f"Skeleton generation failed: {e}")
        return 1
    
    return 0


def main() -> int:
    """Main entry point."""
    # Check required environment variable
    if "DATA_DIR" not in os.environ:
        print("Error: DATA_DIR environment variable must be set", file=sys.stderr)
        print("Example: export DATA_DIR=/path/to/data", file=sys.stderr)
        return 1
    
    # Get repository URL from CLI argument (required)
    if len(sys.argv) < 2:
        raise RuntimeError(
            "Repository URL is required.\n"
            "Usage: python3 scripts/generate_skeleton.py <github_url>"
        )
    
    repo_url = sys.argv[1]
    
    # Validate GitHub URL
    if "github.com" not in repo_url:
        print(f"Error: Only GitHub URLs are supported (got: {repo_url})", file=sys.stderr)
        return 1
    
    return asyncio.run(generate_skeleton(repo_url))


if __name__ == "__main__":
    raise SystemExit(main())
