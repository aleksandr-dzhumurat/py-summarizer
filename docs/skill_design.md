# Skill Design: py-summarizer

## Overview

This document describes the design for packaging `repo_summarizer` as a Claude skill. The skill teaches Claude how to analyze the **current working directory**: generating a structural code skeleton, building call/import graphs, and answering questions about the codebase without loading raw source files into context.

For remote GitHub repositories the full pipeline (clone → skeleton → graph) is also available via standalone scripts.

---

## Skill Identity

| Field | Value |
|-------|-------|
| **name** | `repo-summarizer` (frontmatter) |
| **install folder** | `~/.claude/skills/py-summarizer/` (gist or install.sh) |
| **source folder** | `src/py_summarizer/` |
| **category** | developer-tools |
| **license** | MIT |

**Description (must state WHAT and WHEN, under 1024 chars):**

```
Generates a structural code skeleton (imports, classes, functions), call
graphs, and an architectural summary for the current repository. Use when
the user asks to "analyze this codebase", "summarize the repo",
"generate code skeleton", "map function dependencies",
"who calls function X", or "understand how this project is structured".
```

---

## Skill Folder Structure

The skill ships as three files only — no nested `scripts/` or `src/` inside the skill folder:

```
py-summarizer/          (or repo-summarizer/ depending on install method)
├── SKILL.md            # Required — frontmatter + step-by-step instructions
├── naive_skeleton.py   # AST-based skeleton builder
└── utils.py            # config loading, logging helpers
```

The heavier graph analysis (`code_graph.py`, `retrieval.py`, `generate_code_graph.py`) lives in the project source and is invoked via `scripts/generate_code_graph.py` from the project root.

---

## Current SKILL.md

```markdown
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
  version: 1.0.0
  category: developer-tools
  tags: [code-analysis, call-graph, skeleton]
---

# Repo Summarizer

Analyzes the repository in the current working directory.
All output is written to `.analysis/` inside the project root.

Setup (run once)

```bash
pip install -r requirements.txt
```

---

## Step 1 — Generate code skeleton

Indexes all Python and documentation files and writes a hierarchical
Markdown summary of every file's imports, classes, and functions.

```bash
PYTHONPATH=$HOME/.claude/skills/repo-summarizer python3 $HOME/.claude/skills/repo-summarizer/naive_skeleton.py
```

Pass an optional path to analyze a subdirectory instead of `.`:

```bash
PYTHONPATH=$HOME/.claude/skills/repo-summarizer python3 $HOME/.claude/skills/repo-summarizer/naive_skeleton.py path/to/project
```

Output: `.analysis/skeleton.md`

---

## Step 2 — Generate call graph and architectural summary

**NOTE**: not implemented as skill for now

Builds call/import graphs and an LLM-generated architectural summary.


```bash
DATA_DIR=. PYTHONPATH=$(pwd) python3 scripts/generate_code_graph.py .
```

Output files written to `.analysis/`:
- `ANALYSIS.md` — human-readable architectural report
- `graphs.json` — call and import graph (nodes + edges)
- `summary.json` — structured summary

---

# Manual Usage (without the skill)

Analyze current directory

```bash
# Step 1 — skeleton
PYTHONPATH=$(pwd) python3 -m src.py_summarizer.naive_skeleton

# Step 2 — call graph + summary
DATA_DIR=. PYTHONPATH=$(pwd) python3 scripts/generate_code_graph.py .
```

Analyze an external GitHub repository

```bash
# Step 1 — clone + skeleton
DATA_DIR=./data PYTHONPATH=$(pwd) python3 scripts/generate_skeleton.py {GITHUB_URL}

# Step 2 — call graph + summary
DATA_DIR=./data PYTHONPATH=$(pwd) python3 scripts/generate_code_graph.py {ORG/REPO}
```

Expected output files in `.analysis/` (or `data/{ORG/REPO}/.analysis/`):
- `skeleton.md` — hierarchical code structure
- `graphs.json` — call and import graph edges and nodes
- `summary.json` — structured architectural summary
- `ANALYSIS.md` — human-readable analysis report

---

## Examples

### Example 1: Analyze current project

User says: "Summarize the repo" or "Analyze this codebase"

Actions:
1. Run Step 1 (naive_skeleton.py) on current directory
2. Run Step 2 (generate_code_graph.py) on current directory
3. Read `.analysis/ANALYSIS.md`
4. Present the architectural summary to the user

---

### Example 2: Analyze a remote GitHub repository

User says: "Summarize https://github.com/google/adk-python"

Actions:
1. Run `generate_skeleton.py` with the URL
2. Run `generate_code_graph.py` with `google/adk-python`
3. Read `data/google/adk-python/.analysis/ANALYSIS.md`
4. Present the architectural summary to the user

---

### Example 3: Search for a concept

User says: "Find where sessions are managed"

Pre-condition: Step 1 already completed (skeleton exists).

Actions:
1. Read `.analysis/skeleton.md` and search for "session"
2. Present matching file sections with paths

---

## Troubleshooting

### Error: `DATA_DIR environment variable must be set`
**Cause:** `DATA_DIR` not exported before running the script.
**Fix:** Prefix the command:
```bash
DATA_DIR=. PYTHONPATH=$(pwd) python3 scripts/generate_code_graph.py .
```


---

## Design Decisions

### Local-first, remote-capable

The skill targets the **current working directory** by default — the most common use case when Claude Code is already open in a project. Remote GitHub cloning is still available but requires the full project's scripts (not bundled in the skill).

### Why two separate steps (skeleton vs. graph)?

- Step 1 (skeleton) is fast — AST-only, no LLM, runs in seconds.
- Step 2 (graph) is slower — calls pyan + networkx, optionally calls LLM for summary. Users can run Step 1 alone for quick exploration without needing an API key.

### Why the skill ships only three files?

Keeping `SKILL.md`, `naive_skeleton.py`, and `utils.py` as the skill package means it can be installed from a single gist with no git dependency. The heavier graph analysis stays in the project's `scripts/` and `src/` tree.

### Why TF-IDF and not vector embeddings?

TF-IDF has zero latency, zero API cost, and works offline. The skeleton's structured format (function names, import paths) is well-suited to keyword-based retrieval.

### Progressive disclosure

The skill uses two levels:
1. **SKILL.md frontmatter** — always in context; tells Claude when to trigger
2. **SKILL.md body** — loaded when triggered; contains step-by-step workflow

---

## Output File Reference

All output is written to `.analysis/` inside the analyzed project root:

- `skeleton.md` — Markdown hierarchy of imports/classes/functions per file
- `graphs.json` — `call_graph` and `import_graph` with `nodes` and `edges`
- `summary.json` — structured summary (stats, entry points, top functions)
- `ANALYSIS.md` — human-readable architectural report

---

## Distribution

### Installing in Claude Code (local) — from gist

```bash
mkdir -p ~/.claude/skills/py-summarizer
for f in SKILL.md naive_skeleton.py utils.py; do
  curl -sL "https://gist.githubusercontent.com/aleksandr-dzhumurat/b4435219cca6b1869e0257ef42420273/raw/$f" \
    -o ~/.claude/skills/py-summarizer/$f
done
```

Or with `gh`:

```bash
gh gist clone https://gist.github.com/aleksandr-dzhumurat/b4435219cca6b1869e0257ef42420273 /tmp/repo-summarizer-skill \
  && mkdir -p ~/.claude/skills/py-summarizer \
  && cp /tmp/repo-summarizer-skill/{SKILL.md,naive_skeleton.py,utils.py} ~/.claude/skills/py-summarizer/
```

### Installing in Claude Code (local) — from source

```bash
bash install.sh
```

This copies `src/py_summarizer/` into `~/.claude/skills/py-summarizer/`.

Restart Claude Code after either method. The skill loads automatically.

### Version management

Bump `metadata.version` in `SKILL.md` frontmatter on each release and publish via the `make publish` target (pushes files to the GitHub Gist):

```bash
make publish
git tag skill-v1.1.0
git push origin skill-v1.1.0
```

---

## Implementation Gaps

| Gap | Description | Action |
|-----|-------------|--------|
| `query_function.py` missing | No CLI wrapper for `DocumentIndex.search` / call subgraph queries | Create `scripts/query_function.py` |
