---
name: repo-summarizer
description: >
  Generates a structural code skeleton (imports, classes, functions), call
  graphs, and an architectural summary for the current repository. Use when
  the user asks to "analyze this codebase", "summarize the repo",
  "generate code skeleton", "map function dependencies",
  "who calls function X", or "understand how this project is structured".
license: MIT
allowed-tools: "Bash(*)"
metadata:
  version: 2.1.0
  category: developer-tools
  tags: [code-analysis, call-graph, skeleton, inheritance]
---

# Repo Summarizer

Analyzes the repository in the current working directory.
All output is written to `.analysis/` inside the analyzed repo.

The skill is installed at `~/.claude/skills/py_summarizer/`.

---

## Step 0 — Create environment

```bash
SKILL_DIR="$HOME/.claude/skills/py_summarizer"
python3 -m venv /tmp/py-summarizer-venv && source /tmp/py-summarizer-venv/bin/activate && pip install -r "$SKILL_DIR/skill_requirements.txt" -q
```

---

## Step 1 — Generate code skeleton only

Indexes all Python files and writes a hierarchical Markdown summary of every
file's imports, classes, and functions.

```bash
source /tmp/py-summarizer-venv/bin/activate
PYTHONPATH="$HOME/.claude/skills" python3 -m py_summarizer.naive_skeleton .
```

Output: `.analysis/skeleton.md`

---

## Step 2 — Generate call graph and full analysis

Builds a resolved call graph (function calls + inheritance edges), import
graph, and a fully-rendered LLM summarization prompt.

```bash
source /tmp/py-summarizer-venv/bin/activate
PYTHONPATH="$HOME/.claude/skills" python3 -m py_summarizer .
```

Outputs written to `.analysis/`:
- `summary.json` — machine-readable stats and graph analysis
- `ANALYSIS.md` — human-readable Markdown report
- `graphs.json` — call and import graph edges (source, target, type)
- `rendered_prompt.txt` — fully-rendered LLM summarization prompt

---

## What the call graph captures

| Edge type  | Example                                      |
|------------|----------------------------------------------|
| `calls`    | `app.endpoint` → `py_summarizer.code_graph.analyze_repository` |
| `inherits` | `py_summarizer.code_graph.DiGraph` → `object` |
| `imports`  | `app` → `py_summarizer.code_graph`           |

Call edges are **symbol-resolved**: bare names imported via `from X import Y`
are rewritten to their source module before the graph is built.

---

## Package layout (installed skill)

```
~/.claude/skills/py_summarizer/
    __main__.py         # python3 -m py_summarizer entry point
    naive_skeleton.py   # AST skeleton extraction
    code_graph.py       # DiGraph, call/import/inheritance graph, analyze_repository
    utils.py            # logging, config, file indexing, generate_summarization_prompt
    config.json         # skipped dirs, file extensions, skeleton options
    skill_requirements.txt
```
