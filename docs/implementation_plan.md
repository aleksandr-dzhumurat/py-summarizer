# Implementation Plan: GitHub Python Repo Summarizer

## Current Implementation Status

**Completed (v0):**
- ✅ Repository cloning with git subprocess
- ✅ File indexing with configurable filters
- ✅ Code skeleton generation (AST-based)
- ✅ LLM integration (DeepSeek via Nebius)
- ✅ FastAPI REST API
- ✅ CLI scripts
- ✅ Configuration management (YAML)

**Planned (Future):**
- ⏳ LLM-guided repo observer
- ⏳ Advanced AST extractor
- ⏳ Call graph analysis (pyan3 + networkx)
- ⏳ Multi-track summarization

## Architecture Overview

```
Client → POST /summarize → FastAPI → Synchronous Pipeline → Return Results

Current Pipeline:
  clone_repo → get_index → code_skeleton → llm.call → return JSON
       ↓            ↓            ↓              ↓
   git clone   filter files   AST parse   DeepSeek API

Future Pipeline:
  clone_repo → repo_observer → ast_extractor → pyan3 call graph
                    ↓                ↓               ↓
               priority map     module skeletons   call edges
                    └──────────────┴───────────────┘
                                   ↓
                             networkx graph
                                   ↓
                            llm summarizer
                                   ↓
                          return results
```

---

## Current Project Structure

```
repo_summarizer/
├── src/
│   ├── app.py                # FastAPI application (implemented)
│   ├── utils.py              # Utilities: logging, config, cloning, indexing (implemented)
│   ├── naive_skeleton.py     # Code skeleton generation using AST (implemented)
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── llm_adapter.py    # DeepSeek LLM adapter (implemented)
│   │   ├── models.py         # RepositorySummary, ComponentInfo (implemented)
│   │   └── prompts.py        # repo_summarizer_prompt (implemented)
│   └── __pycache__/
├── scripts/
│   ├── main.py               # CLI entry point (implemented)
│   ├── generate_skeleton.py  # Skeleton-only script (implemented)
│   ├── test_api.py           # API testing
│   └── README.md
├── config.yml                # YAML configuration (implemented)
├── requirements.txt          # Dependencies
├── .env                      # Environment variables (NEBIUS_API_KEY)
├── Makefile                  # Build automation
├── README.md                 # Documentation
├── implementation_plan.md    # This file
├── implementation_plan_stage_1.md  # Multi-task queue plan (future)
└── data/                     # Cloned repositories (gitignored)
```

---

## Phase 1 — Models (Implemented)

### Current Models (`src/llm/models.py`)

```python
class ComponentInfo(BaseModel):
    """Information about a code component."""
    name: str = Field(..., description="Component name")
    role: str = Field(..., description="Component role in the system")

class RepositorySummary(BaseModel):
    """Structured summary of a GitHub repository."""
    summary: str = Field(..., description="Concise overview")
    technologies: list[str] = Field(..., description="Technologies used")
    structure: str = Field(..., description="Project structure")
    key_components: Optional[list[ComponentInfo]] = Field(default=None)
    design_patterns: Optional[list[str]] = Field(default=None)
```

### API Models (`src/app.py`)

```python
class SummarizeRequest(BaseModel):
    github_url: HttpUrl

class SummarizeResponse(BaseModel):
    task_id: str
    status: str
    message: str
    summary: dict | None = None
    stats: dict | None = None
```

### Future Models (Planned)

```python
class ModuleSkeleton(BaseModel):
    file: str
    module_name: str
    classes: list[ClassInfo]
    functions: list[str]
    imports_internal: list[str]
    imports_external: list[str]
    line_count: int
    importance_score: int

class RepoStats(BaseModel):
    total_files: int
    total_lines: int
    total_functions: int
    total_classes: int
    external_dependencies: list[str]
    entry_points: list[str]
    test_ratio: float
    has_type_hints: bool
```

---

## Phase 2 — API Endpoints (Implemented)

### Current Implementation (`src/app.py`)

```python
app = FastAPI(
    title="GitHub Repository Summarizer",
    description="Analyze GitHub repositories and generate LLM-based summaries",
    version="0.1.0"
)

@app.post("/summarize", response_model=SummarizeResponse)
async def summarize_repo(request: SummarizeRequest) -> SummarizeResponse:
    """
    Analyze a GitHub repository and generate a summary.
    
    Executes synchronously: clone → index → skeleton → LLM → return results.
    """
    repo_url = str(request.github_url)
    task_id = str(uuid.uuid4())
    
    if "github.com" not in repo_url:
        raise HTTPException(status_code=400, detail="Only GitHub URLs supported")
    
    # Run analysis synchronously
    result = await run_pipeline(task_id, repo_url)
    
    return SummarizeResponse(
        task_id=task_id,
        status="finished",
        message=f"Analysis completed for {repo_url}.",
        summary=result.get("summary"),
        stats=result.get("stats"),
    )

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}
```

### Pipeline Implementation

```python
async def run_pipeline(task_id: str, repo_url: str) -> dict:
    """Execute the full analysis pipeline."""
    repo_path = None
    try:
        # Clone repository
        repo_path = await clone_repo(repo_url, timeout=180)
        
        index = get_index(str(repo_path))
        
        skeleton = code_skeleton(index, str(repo_path))
        
        # LLM summarization
        llm = DeepSeekLLMAdapter()
        prompt = repo_summarizer_prompt(skeleton)
        summary_text = await llm.call(prompt)
        summary = json.loads(summary_text)
        
        return {
            "summary": summary,
            "stats": {"total_files": len(index), "skeleton_size": len(skeleton)}
        }
    finally:
        # Cleanup cloned repo
        if repo_path and repo_path.exists():
            shutil.rmtree(repo_path, ignore_errors=True)
```

---

## Phase 3 — Utilities (Implemented)

### Cloning (`src/utils.py`)

```python
async def clone_repo(repo_url: str, timeout: int = 120) -> Path:
    """
    Clone repo to DATA_DIR/<owner>/<repo>.
    Skips if already exists. Uses asyncio.subprocess for git clone.
    """
    base_dir = os.environ["DATA_DIR"]
    base_path = Path(base_dir)
    base_path.mkdir(parents=True, exist_ok=True)
    
    # Extract owner/repo from URL
    slug = repo_url.rstrip("/").split("github.com/")[-1].removesuffix(".git")
    target_path = base_path.joinpath(*slug.split("/"))
    
    # Skip if already cloned
    if target_path.exists():
        return target_path
    
    # Clone with depth=1
    cmd = ["git", "clone", "--depth=1", "--single-branch", "--no-tags", 
           repo_url, str(target_path)]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    
    if proc.returncode != 0:
        shutil.rmtree(target_path, ignore_errors=True)
        raise RuntimeError(f"Clone failed: {stderr.decode()}")
    
    return target_path
```

### File Indexing (`src/utils.py`)

```python
def get_index(root_dir_path: str) -> list[dict[str, str]]:
    """
    Return list of {"file_path": "relative/path"} for files in directory.
    
    Filters:
    - Skips dot-prefixed files/dirs
    - Skips dirs in config.yml skipped_dirs
    - Only includes files with extensions in config.yml text_extensions
    """
    root = Path(root_dir_path).resolve()
    results = []
    
    excluded_dirs = {d.lower() for d in get_skipped_dirs()}
    text_extensions = {ext.lower() for ext in get_text_extensions()}
    
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames 
                      if not d.startswith('.') and d.lower() not in excluded_dirs]
        
        for fname in filenames:
            if fname.startswith('.'):
                continue
            
            full = Path(dirpath) / fname
            ext = full.suffix.lower()
            
            if ext and ext not in text_extensions:
                continue
            
            rel = full.relative_to(root).as_posix()
            results.append({"file_path": rel})
    
    return results
```

### Configuration (`src/utils.py`)

```python
def load_config(config_path: Optional[Path] = None) -> dict:
    """Load config.yml with fallback defaults."""
    if config_path is None:
        config_path = Path(__file__).parent.parent / "config.yml"
    
    if not config_path.exists():
        return {"skipped_dirs": [...], "text_extensions": [".py"], ...}
    
    with open(config_path, "r") as f:
        return yaml.safe_load(f) or {}

def get_skipped_dirs() -> list[str]:
    """Get directories to exclude from indexing."""
    return load_config().get("skipped_dirs", [])

def get_text_extensions() -> list[str]:
    """Get file extensions to include."""
    return load_config().get("text_extensions", [".py"])

def get_class_methods_flag() -> bool:
    """Whether to include class methods in skeleton."""
    return load_config().get("class_methods", False)
```

### Configuration File (`config.yml`)

```yaml
skipped_dirs:
  - example
  - examples  
  - test
  - ...

text_extensions:
  - .py
  - .txt
  - .md
  - .rst
  - .json
  - .yaml
  - .yml
  - .toml

class_methods: false
max_docstring_length: 120

clone_timeout: 180
clone_depth: 1
cleanup_repo_after_processing: true

llm:
  model: "deepseek-ai/DeepSeek-V3.2"
  api_base: "https://api.tokenfactory.nebius.com/v1/chat/completions"
  timeout: 60
  max_prompt_tokens: 50000
  temperature: 0.7
  max_tokens: 2048
```

---

## Phase 4 — Code Skeleton Generation (Implemented)

### Current Implementation (`src/naive_skeleton.py`)

Uses Python's AST to extract structure from indexed files:

```python
def code_skeleton(index: list[dict[str, str]], root_dir: str) -> str:
    """
    Generate code skeleton from indexed files.
    
    For Python files:
    - Parse with ast module
    - Extract imports (exclude stdlib)
    - Extract top-level functions
    - Extract classes (optionally methods if class_methods=true)
    - Skip docstrings > max_docstring_length
    
    For non-Python files:
    - Include first 10 lines as comment block
    """
    root_path = Path(root_dir).resolve()
    skipped = {d.lower() for d in get_skipped_dirs()}
    class_methods = get_class_methods_flag()
    max_doc_len = load_config().get("max_docstring_length", 120)
    
    result = []
    
    for item in index:
        rel_path = item["file_path"]
        full_path = root_path / rel_path
        
        # Skip if parent directory is in skipped_dirs
        if any(part.lower() in skipped for part in Path(rel_path).parts):
            continue
        
        result.append(f"\n# File: {rel_path}")
        
        if full_path.suffix != ".py":
            # Non-Python: include first 10 lines
            try:
                with open(full_path, encoding="utf-8", errors="ignore") as f:
                    lines = [f"# {line.rstrip()}" for line in islice(f, 10)]
                    result.extend(lines)
            except Exception:
                result.append("# (read error)")
            continue
        
        # Parse Python files with AST
        try:
            with open(full_path, encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=str(rel_path))
        except Exception:
            result.append("# (parse error)")
            continue
        
        # Extract imports (exclude stdlib)
        imports = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if not _is_stdlib(alias.name):
                        imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module and not _is_stdlib(node.module):
                    imports.append(node.module)
        
        if imports:
            result.append(f"# Imports: {', '.join(sorted(set(imports)))}")
        
        # Extract functions
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                result.append(f"\ndef {node.name}{_signature(node)}:")
                _add_docstring(result, node, max_doc_len)
                result.append("    ...")
        
        # Extract classes
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                bases = [_expr_to_str(b) for b in node.bases]
                base_str = f"({', '.join(bases)})" if bases else ""
                result.append(f"\nclass {node.name}{base_str}:")
                _add_docstring(result, node, max_doc_len)
                
                if class_methods:
                    # Include methods if enabled
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef):
                            result.append(f"    def {item.name}{_signature(item)}:")
                            _add_docstring(result, item, max_doc_len, indent=8)
                            result.append("        ...")
                else:
                    result.append("    ...")
    
    return "\n".join(result)

def _is_stdlib(module_name: str) -> bool:
    """Check if module is in Python stdlib (Python 3.10+)."""
    return module_name.split(".")[0] in sys.stdlib_module_names
```

### Helpers

```python
def _signature(node: ast.FunctionDef) -> str:
    """Extract function signature."""
    args = []
    for arg in node.args.args:
        args.append(arg.arg)
    return f"({', '.join(args)})"

def _expr_to_str(expr: ast.expr) -> str:
    """Convert AST expression to string."""
    if isinstance(expr, ast.Name):
        return expr.id
    elif isinstance(expr, ast.Attribute):
        return ast.unparse(expr)
    return ""

def _add_docstring(result: list[str], node, max_len: int, indent: int = 4):
    """Add docstring if present and within length limit."""
    doc = ast.get_docstring(node)
    if doc:
        doc = doc.strip()
        if len(doc) <= max_len:
            spaces = " " * indent
            result.append(f'{spaces}"""{doc}"""')
```

---

## Phase 5 — LLM Integration (Implemented)

### DeepSeek Adapter (`src/llm/llm_adapter.py`)

```python
class DeepSeekLLMAdapter:
    """DeepSeek LLM adapter using OpenAI-compatible API."""
    
    def __init__(self):
        self.api_key = os.getenv("NEBIUS_API_KEY")
        self.base_url = load_config().get("llm", {}).get("api_base")
        self.model = load_config().get("llm", {}).get("model", "deepseek-ai/DeepSeek-V3.2")
        self.timeout = load_config().get("llm", {}).get("timeout", 60)
        self.max_prompt_tokens = load_config().get("llm", {}).get("max_prompt_tokens", 50000)
        self.client = httpx.AsyncClient(timeout=self.timeout)
    
    async def call(
        self,
        prompt: str,
        response_model: Type[BaseModel] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048
    ) -> str:
        """Call LLM with prompt and optional structured output."""
        # Validate prompt token count
        self._validate_prompt_tokens(prompt)
        
        # Build request
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        
        # Add JSON schema for structured output
        if response_model:
            schema = pydantic_to_json_schema(response_model)
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": response_model.__name__,
                    "strict": True,
                    "schema": schema
                }
            }
        
        # Make request
        resp = await self.client.post(
            self.base_url,
            headers=headers,
            json=payload
        )
        resp.raise_for_status()
        
        # Extract response
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return content.strip()
    
    def _validate_prompt_tokens(self, prompt: str) -> None:
        """Check if prompt exceeds token limit."""
        enc = tiktoken.encoding_for_model("gpt-4")
        tokens = enc.encode(prompt)
        if len(tokens) > self.max_prompt_tokens:
            raise ValueError(
                f"Prompt too long: {len(tokens)} tokens (limit: {self.max_prompt_tokens})"
            )
    
    async def summarize_repository(self, skeleton_text: str) -> RepositorySummary:
        """Generate structured repository summary."""
        prompt = repo_summarizer_prompt(skeleton_text)
        response_text = await self.call(
            prompt,
            response_model=RepositorySummary,
            temperature=0.7,
            max_tokens=2048
        )
        return RepositorySummary.model_validate_json(response_text)
```

### Prompt Template (`src/llm/prompts.py`)

```python
def repo_summarizer_prompt(skeleton_text: str) -> str:
    """Generate prompt for repository summarization."""
    return f"""You are a code analysis assistant. Analyze the following code skeleton and provide a structured summary.

Code Skeleton:
{skeleton_text}

Provide:
1. A concise summary (2-3 sentences) of what this repository does
2. List of technologies/frameworks used
3. Description of the project structure and organization
4. Key components with their roles (name and role for each)
5. Design patterns identified

Return your analysis as valid JSON matching the schema.
"""
```

---

## Phase 6 — Testing & Validation (Implemented)

### CLI Usage (`scripts/main.py`)

```bash
# Analyze repository via CLI
python scripts/main.py https://github.com/psf/requests

# Output: SUMMARY.json, SKELETON.txt in cloned repo directory
```

### API Usage

```bash
# Start server
make serve
# or
uvicorn src.app:app --host 0.0.0.0 --port 8000 --reload

# Test endpoint
curl -X POST http://localhost:8000/summarize \
  -H "Content-Type: application/json" \
  -d '{"github_url": "https://github.com/psf/requests"}'

# Response:
{
  "task_id": "abc-123",
  "status": "finished",
  "message": "Analysis completed for https://github.com/psf/requests.",
  "summary": {
    "summary": "Python HTTP library...",
    "technologies": ["Python", "HTTP", "Requests"],
    "structure": "...",
    "key_components": [...],
    "design_patterns": [...]
  },
  "stats": {
    "total_files": 42,
    "skeleton_size": 1234
  }
}
```

### Makefile Commands

```makefile
serve:          # Start FastAPI server
    uvicorn src.app:app --host 0.0.0.0 --port 8000 --reload

run:            # Run CLI analysis
    python scripts/main.py https://github.com/psf/requests

test-api:       # Test API with example repo
    python scripts/test_api.py

lint:           # Run code quality checks
    ruff check src/ scripts/

format:         # Format code
    ruff format src/ scripts/
```

---

## Future Enhancements (Planned)

### Stage 1: Multi-Task Queue

See `implementation_plan_stage_1.md` for full details:

- SQLite task queue with status tracking
- Background workers for async processing  
- GET /tasks/{task_id} endpoint for polling
- Stage-based pipeline: CLONE → INDEX → SKELETON → LLM → DONE
- Multiple repos can be queued simultaneously

### Stage 2: Advanced Analysis

**Repo Observer** (`src/repo_observer.py`):
- LLM-guided structure analysis from README/pyproject.toml
- Extract entry points and dependencies
- Priority mapping for important files (score 1-10)
- Output: StructureMap with priority_files list

**AST Extractor** (`src/ast_extractor.py`):
- Deep AST parsing for priority files only
- Extract module-level functions, classes, methods with signatures
- Track internal vs. external imports with path resolution
- Compute importance scores based on usage patterns
- Output: ModuleSkeleton with detailed class/function info

**Call Graph** (`src/call_graph.py`):
- Use pyan3 to analyze function call chains
- Build networkx DiGraph of call edges
- Identify central nodes (PageRank, betweenness centrality)
- Find orchestrator functions (high out-degree)
- Detect isolated subsystems (weakly connected components)
- Output: GraphViz visualization + networkx graph queries

**Import Layer Analysis**:
- Build module-level import graph (networkx)
- Find foundation modules (imported by many, import nothing)
- Find orchestration modules (import many others)
- Detect circular dependencies
- Output: Architectural layer hierarchy

### Stage 3: Multi-Track Summarization

**Documentation Track**:
- README, CONTRIBUTING, setup.py analysis
- Extract project goals, usage examples
- Identify target audience

**Code Track** (replaces current simple skeleton):
- Top N files by importance score
- AST skeletons with call graph signals
- Import layer analysis
- Entry point detection

**Quality Track**:
- Type hint coverage percentage
- Docstring completeness
- Test file ratio (tests/ vs src/)
- Async/await usage patterns

**Dependencies Track**:
- External package analysis
- Version constraints from requirements.txt
- License compatibility checks

**Final Synthesis**:
- Merge all tracks into comprehensive report
- Identify architecture patterns (layered, hexagonal, pipeline)
- Detect design patterns (repository, DI, factory, observer)
- Assess complexity (cyclomatic, call chain depth)
- Generate recommendations

---

## Conclusion

The current implementation (v0) provides a solid foundation:

**✅ Completed:**
- Fast, synchronous analysis pipeline
- Configuration-driven (YAML)
- Clean, consolidated codebase (~220 lines of dead code removed)
- REST API + CLI interfaces
- LLM-powered summarization (DeepSeek via Nebius)
- AST-based skeleton generation (stdlib-only, Python 3.10+)
- File indexing with smart filters
- Shallow git cloning (--depth=1)

**⏳ Future Stages:**
- Async task queue for long-running jobs (SQLite)
- LLM-guided repo exploration (observer)
- Advanced AST analysis with call graphs (pyan3 + networkx)
- Multi-dimensional quality metrics
- Architectural pattern detection
- Import layer analysis

**Dependencies:**
```
fastapi>=0.95.0
uvicorn>=0.22.0
pydantic>=2.0.0
PyYAML>=6.0.0
httpx>=0.24.0
tiktoken>=0.4.0
python-dotenv>=1.0.0
```

**Future Dependencies:**
```
pyan3          # Call graph analysis
networkx       # Graph queries
anthropic      # Multi-track LLM calls (optional alternative to DeepSeek)
```

**Key Design Decisions:**
1. Python 3.10+ required (sys.stdlib_module_names)
2. No GitPython (asyncio.subprocess instead)
3. No language-agnostic parsers (Python-focused)
4. Configuration over hardcoding (config.yml)
5. Structured LLM outputs (Pydantic models + JSON schema)
6. Token budget validation (tiktoken)
7. Single-file utilities consolidation (src/utils.py)

See `implementation_plan_stage_1.md` for detailed SQLite queue architecture and async processing design.