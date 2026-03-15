# GitHub Repository Summarizer

A tool that clones GitHub repositories, analyzes their structure, and generates LLM-based summaries.

# Agentic skill

The `py_summarizer` skill teaches Claude to analyze any Python repository: generating a structural code skeleton, call/import graphs, and an LLM architectural summary — without loading raw source files into context.

### Install from Gist (no clone needed)

```bash
mkdir -p ~/.claude/skills/py_summarizer
for f in SKILL.md naive_skeleton.py utils.py code_graph.py __main__.py config.json skill_requirements.txt; do
  curl -sL "https://gist.githubusercontent.com/aleksandr-dzhumurat/b4435219cca6b1869e0257ef42420273/raw/$f" \
    -o ~/.claude/skills/py_summarizer/$f
done
```

Restart Claude Code (just open a new chat) after installation. Then ask:
> "Analyze this codebase" or "Summarize the repo"

2nd option: clone repo and run installation script

```bash
bash install.sh
```
## Manual usage (without the skill)


First - install dependencies

```bash
pip install -r requirements.txt
```

Set your API key for the architectural summary step:

```bash
export NEBIUS_API_KEY=****
```

Configure [`config.json`](src/py_summarizer/config.json) to adjust what the skeleton includes
(imports, functions, classes, directories to skip):

```json
{
  "import": { "relative_imports": true, "absolute_imports": true },
  "classes": { "definitions": true, "methods": true },
  "functions": true
}
```


Summarizing any python module

```shell
PYTHONPATH=$(pwd)/src python3 -m py_summarizer.naive_skeleton /path/to/your/python/module
```

Generate call graph and architectural summary:

```bash
PYTHONPATH=$(pwd)/src DATA_DIR=./data python3 scripts/generate_code_graph.py google/adk-python
```

Output is written to `.analysis/` — `summary.json`, `ANALYSIS.md`, `graphs.json`, `rendered_prompt.txt`.


### HTTP service usage

Supports deployment as either a FastAPI service (not only via agent skill).

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
- `src/py_summarizer/` - Code skeleton and graph analysis
- `src/llm/` - LLM adapter and prompts
- `scripts/` - CLI entry points
- `data/` - Cloned repositories storage


## Features

- Clone and analyze GitHub repositories
- Generate code structure skeletons
- Create AI-powered summaries using Anthropic Claude
- FastAPI REST API for programmatic access
- CLI script for direct execution

## Requirements

- Python 3.8+
- Git (for cloning repositories)
- uv package manager
- Valid NEBIUS_API_KEY for LLM access
