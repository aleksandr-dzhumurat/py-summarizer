#!/usr/bin/env python3
"""
Repository Code Graph Analyzer

Extracts AST skeletons, resolves call/inheritance edges, builds call and import
graphs, and saves results to <repo>/.analysis/:

    summary.json        - repo stats and graph analysis
    ANALYSIS.md         - markdown report
    graphs.json         - serialized call and import graphs
    rendered_prompt.txt - LLM-ready summarization prompt

To generate an LLM summary from the prompt, run generate_llm_summary.py next.

Usage:
    python3 scripts/generate_code_graph.py <repo_path>

Environment variables:
    DATA_DIR: Directory where repositories are located (required)

Example:
    PYTHONPATH=$(pwd)/src DATA_DIR=./data python3 scripts/generate_code_graph.py google/adk-python
"""

import os
import sys
from pathlib import Path

from py_summarizer.code_graph import (
    analyze_repository,
    export_graph,
    export_json,
    export_markdown,
)

# ============================================================================
# CLI Entry Point
# ============================================================================

def main() -> int:
    # Check required environment variable
    if "DATA_DIR" not in os.environ:
        print("Error: DATA_DIR environment variable must be set", file=sys.stderr)
        print("Example: export DATA_DIR=./data", file=sys.stderr)
        return 1

    if len(sys.argv) < 2:
        print("Usage: python3 scripts/generate_code_graph.py <repo_path> [--api-key YOUR_KEY]", file=sys.stderr)
        print("Example: DATA_DIR=./data python3 scripts/generate_code_graph.py google/adk-python", file=sys.stderr)
        return 1

    # Resolve repository path relative to DATA_DIR
    data_dir = Path(os.environ["DATA_DIR"])
    repo_relative_path = sys.argv[1]
    repo_path = data_dir / repo_relative_path

    if not repo_path.exists():
        print(f"Error: Repository path does not exist: {repo_path}", file=sys.stderr)
        return 1

    summary, call_graph, import_graph, rendered_prompt = analyze_repository(str(repo_path))

    output_dir = Path(repo_path) / ".analysis"
    output_dir.mkdir(exist_ok=True)

    export_json(summary, output_dir / "summary.json")
    export_markdown(summary, output_dir / "ANALYSIS.md")
    export_graph(call_graph, import_graph, output_dir / "graphs.json")

    prompt_path = output_dir / "rendered_prompt.txt"
    prompt_path.write_text(rendered_prompt, encoding="utf-8")
    print(f"Saved rendered prompt to: {prompt_path}")

    print("\n" + "=" * 70)
    print("ANALYSIS COMPLETE")
    print("=" * 70)
    print(f"Results saved to: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())