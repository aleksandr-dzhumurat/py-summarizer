# GitHub Repository Summarizer

A tool that clones GitHub repositories, analyzes their structure, and generates LLM-based summaries.

Supports deployment as either a FastAPI service or an agent skill.

Summarizing any python module

```shell
PYTHONPATH=$(pwd)/src/py_summarizer python3 -m src.py_summarizer.naive_skeleton /Users/adzhumurat/PycharmProjects/ai_product_engineer/src/assistant
```

# Agentic skill

The `repo-summarizer` skill teaches Claude to analyze any Python repository
in the current working directory: generating a structural code skeleton,
call/import graphs, and an LLM architectural summary — without loading raw
source files into context.

### Install from Gist (no clone needed)

```bash
mkdir -p ~/.claude/skills/py-summarizer
for f in SKILL.md naive_skeleton.py utils.py; do
  curl -sL "https://gist.githubusercontent.com/aleksandr-dzhumurat/b4435219cca6b1869e0257ef42420273/raw/$f" \
    -o ~/.claude/skills/py-summarizer/$f
done
```

Restart Claude Code after installation. Then ask:
> "Analyze this codebase" or "Summarize the repo"

### Install from source

```bash
bash install.sh
```

This copies `src/py_summarizer/` into `~/.claude/skills/repo-summarizer/`.

## Install


## Dependencies

```bash
pip install -r requirements.txt
```

Set your Anthropic API key for the architectural summary step:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Configure [`config.yml`](config.yml) to adjust what the skeleton includes
(imports, functions, classes, directories to skip):

```yaml
import:
  relative_imports: true
  absolute_imports: true

classes:
  definitions: true
  methods: true

functions: true
```

## Manual usage (without the skill)

Generate code skeleton for the current directory:

```bash
PYTHONPATH=$(pwd) python3 -c "
import asyncio; from pathlib import Path
from src.py_summarizer.naive_skeleton import skeleton_pipeline
asyncio.run(skeleton_pipeline(Path('.')))
"
```

Generate call graph and architectural summary:

```bash
DATA_DIR=. PYTHONPATH=$(pwd) python3 scripts/generate_code_graph.py .
```

Output is written to `.analysis/` — `skeleton.md`, `graphs.json`, `ANALYSIS.md`.


### 2. Usage

Start the FastAPI server:

```bash
make serve
```

The server runs on `http://0.0.0.0:8000`

Test the API (take up to 10 seconds for huge repo)

```bash
curl -X POST http://localhost:8000/summarize \
  -H "Content-Type: application/json" \
  -d '{"github_url": "https://github.com/psf/requests"}' | python3 -m json.tool
```

# Deployment

Using git archive (respects .gitignore)

```shell
git archive --format=zip -o repo_summarizer.zip HEAD
```

## API Endpoints

**POST /summarize**
- Request: `{"github_url": "https://github.com/owner/repo"}`
- Response: Returns task_id, status, summary, and statistics
- Analyzes the repository and returns results

**GET /health**
- Returns server health status


This runs a smoke test that checks the health endpoint and submits a summarization request.

## Makefile Commands

| Command | Description |
|---------|-------------|
| `make prepare-dirs` | Create the data directory |
| `make run REPO=<url>` | Run CLI summarizer on a repository |
| `make serve` | Start the FastAPI server with auto-reload |
| `make test-api` | Run API smoke tests |
| `make gh-login` | Authenticate with GitHub (`gh auth login`) |
| `make publish` | Publish skill files to GitHub Gist |

## Project Structure

- `src/app.py` - FastAPI application
- `src/utils.py` - Utility functions (logging, cloning)
- `src/crawler/` - Repository indexing and skeleton generation
- `src/llm/` - LLM adapter and prompts
- `scripts/main.py` - CLI entry point
- `scripts/test_api.py` - API testing script
- `data/` - Cloned repositories storage


## Features

- Clone and analyze GitHub repositories
- Generate code structure skeletons
- Create AI-powered summaries using DeepSeek LLM
- FastAPI REST API for programmatic access
- CLI script for direct execution

DeepSeek-V3.2 was chosen for its excellent performance on code understanding tasks and cost-effectiveness compared to other frontier models.

## Requirements

- Python 3.8+
- Git (for cloning repositories)
- uv package manager
- Valid NEBIUS_API_KEY for LLM access
