"""Async runner that clones a GitHub repo and produces a summary.

This is a relocated copy of `src/main.py` moved to `scripts/` so it can be
invoked directly (for example via `python3 scripts/main.py <repo_url>`).
"""

import asyncio
import json
import sys

from src.llm import DeepSeekLLMAdapter
from src.py_summarizer.naive_skeleton import code_skeleton
from src.py_summarizer.utils import clone_repo, get_index

# Default repo if none provided via CLI
DEFAULT_REPO_URL = "https://github.com/databricks-solutions/ai-dev-kit"


async def run(repo_url: str) -> int:
    print(f"Repository: {repo_url}\n")
    try:
        path = await clone_repo(repo_url, timeout=180)
    except Exception as exc:
        print(f"Clone failed: {exc}")
        return 1

    print(f"Cloned repository to: {path}")
    # Basic sanity check: ensure README or setup.py exists
    if any((path / name).exists() for name in ("README.md", "setup.py", "pyproject.toml")):
        print("Basic repo files detected.")
    else:
        print("Warning: common top-level files not detected.")

    # Keep the cloned repository on disk for inspection. Do not remove it.
    print(f"Clone retained at: {path}")

    # Index the repository files and show a brief summary
    try:
        indexed = get_index(str(path))
        print(f"Indexed {len(indexed)} files.")
        if indexed:
            sample = indexed[:10]
            print("Sample files:")
            for entry in sample:
                print(" -", entry.get("file_path"))
    except Exception as e:
        print(f"Indexing failed: {e}")

    # Generate a naive code skeleton from the index and save it into the repo
    try:
        skeleton_text = code_skeleton(indexed, root_dir=str(path))
        # Print a short preview (first 40 lines)
        preview = "\n".join(skeleton_text.splitlines()[:40])
        print("\n=== Skeleton preview ===\n")
        print(preview)

        analysis_dir = path / ".analysis"
        analysis_dir.mkdir(exist_ok=True)
        out_file = analysis_dir / "skeleton.txt"
        out_file.write_text(skeleton_text, encoding="utf-8")
        print(f"Full skeleton written to: {out_file}")
    except Exception as e:
        print(f"Skeleton generation failed: {e}")

    # Generate a repository summary using LLM
    try:
        print("\n=== Generating LLM summary ===\n")
        adapter = DeepSeekLLMAdapter()
        summary = await adapter.summarize_repository(skeleton_text)
        
        summary_file = path / "SUMMARY.json"
        with open(summary_file, "w", encoding="utf-8") as f:
            # Convert Pydantic model to dict for JSON serialization
            json.dump(summary.model_dump(), f, indent=2, ensure_ascii=False)
        
        print(f"Summary written to: {summary_file}")
        if isinstance(summary, dict) and "summary" in summary:
            print(f"Project: {summary.get('summary', 'N/A')[:100]}...")
        else:
            # summary may be a Pydantic model - try to access attributes safely
            try:
                s = getattr(summary, "summary", None)
                if s:
                    print(f"Project: {s[:100]}...")
            except Exception:
                pass
    except ValueError as e:
        print(f"LLM summarization skipped (API key not configured): {e}")
    except Exception as e:
        print(f"Summary generation failed: {e}")

    return 0


if __name__ == "__main__":
    # Get repo URL from CLI argument or use default
    repo_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_REPO_URL
    raise SystemExit(asyncio.run(run(repo_url)))
