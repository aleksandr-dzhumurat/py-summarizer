---
name: repo-summarizer
description: >
  Generates a structural code skeleton (imports, classes, functions), call
  graphs, and an architectural summary for the current repository. Use when
  the user asks to "analyze this codebase", "summarize the repo",
  "generate code skeleton", "map function dependencies",
  "who calls function X", or "understand how this project is structured".
license: MIT
allowed-tools: "Bash(python3:*)"
metadata:
  version: 2.0.0
  category: developer-tools
  tags: [code-analysis, call-graph, skeleton, inheritance]
---

# Repo Summarizer

Analyzes the repository in the current working directory.
All output is written to `.analysis/` inside the project root.

---

## Step 1 — Generate code skeleton

Indexes all Python and documentation files and writes a hierarchical
Markdown summary of every file's imports, classes, and functions.

```bash
PYTHONPATH=. python3 -m src.py_summarizer.naive_skeleton [PATH]
```

Omit `PATH` to analyze the current directory. Output: `.analysis/skeleton.md`

To analyze a remote GitHub repository (clones first):

```bash
DATA_DIR=./data PYTHONPATH=. python3 scripts/generate_skeleton.py https://github.com/owner/repo
```

---

## Step 2 — Generate call graph and full analysis

Builds a resolved call graph (function calls + inheritance edges) and an
import graph, then generates a structured JSON, Markdown report, and
LLM-produced architectural summary.

```bash
DATA_DIR=./data PYTHONPATH=. python3 scripts/generate_code_graph.py owner/repo [--api-key YOUR_KEY]
```

`ANTHROPIC_API_KEY` is read from the environment if `--api-key` is omitted.

Outputs written to `<repo>/.analysis/`:
- `skeleton.md` — hierarchical code skeleton
- `summary.json` — machine-readable stats and graph analysis
- `ANALYSIS.md` — human-readable Markdown report
- `graphs.json` — call and import graph edges (source, target, type)

---

## What the call graph captures

| Edge type  | Example                                      |
|------------|----------------------------------------------|
| `calls`    | `src.app.endpoint` → `src.py_summarizer.code_graph.analyze_repository` |
| `inherits` | `src.py_summarizer.code_graph.DiGraph` → `object` |
| `imports`  | `src.app` → `src.py_summarizer.code_graph`   |

Call edges are **symbol-resolved**: bare names imported via `from X import Y`
are rewritten to their source module before the graph is built, so
`get_subgraph` becomes `src.py_summarizer.code_graph.get_subgraph`.

---

## Package layout

```
src/py_summarizer/
    naive_skeleton.py   # AST skeleton extraction + skeleton_pipeline entry point
    code_graph.py       # DiGraph, call/import/inheritance graph, analyze_repository
    utils.py            # logging, config loading, file indexing, clone_repo

scripts/
    generate_skeleton.py    # clone + skeleton only
    generate_code_graph.py  # full analysis (skeleton + graphs + LLM summary)
```
