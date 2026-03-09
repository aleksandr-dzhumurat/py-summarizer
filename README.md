# GitHub Repository Summarizer

A tool that clones GitHub repositories, analyzes their structure, and generates LLM-based summaries.

Supports deployment as either a FastAPI service or an agent skill.

## Setup

### 1. Environment Configuration

Create a `.env` file with required configuration:

```bash
NEBIUS_API_KEY=your_api_key_here
MAX_PROMPT_TOKENS=6000
# this vas is used by API testing scripts
REPO=https://github.com/psf/requests
```
Install dependencies and activate env

```bash
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

Configure [`config.yml`](config.yml) to customize skeleton generation (imports, functions, classes, directories to skip, etc.).


```yaml
import:
  relative_imports: true
  absolute_imports: true

classes:
  definitions: true
  methods: true

functions: true

max_docstring_length: 120
```


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

## Project Structure

- `src/app.py` - FastAPI application
- `src/utils.py` - Utility functions (logging, cloning)
- `src/crawler/` - Repository indexing and skeleton generation
- `src/llm/` - LLM adapter and prompts
- `scripts/main.py` - CLI entry point
- `scripts/test_api.py` - API testing script
- `data/` - Cloned repositories storage

## Workflow

On each request
- process Clone the repository to `data/`
- Index all files
- Generate a code skeleton
- Create an LLM-based summary

test separately
```shell
DATA_DIR=./data PYTHONPATH=. python3 scripts/generate_skeleton.py https://github.com/microsoft/agent-lightning
```


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
