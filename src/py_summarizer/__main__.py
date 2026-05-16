"""Entry point: python3 -m py_summarizer [PATH]"""
import sys
from pathlib import Path

from .code_graph import analyze_repository, export_json, export_markdown, export_graph


def main() -> int:
    repo_path = str(Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve())

    summary, call_graph, import_graph, rendered_prompt = analyze_repository(repo_path)

    output_dir = Path(repo_path) / ".analysis"
    output_dir.mkdir(exist_ok=True)

    export_json(summary, output_dir / "summary.json")
    export_markdown(summary, output_dir / "ANALYSIS.md")
    export_graph(call_graph, import_graph, output_dir / "graphs.json")
    (output_dir / "rendered_prompt.txt").write_text(rendered_prompt, encoding="utf-8")

    print(f"\nAnalysis complete. Results saved to: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
