# Strategy for Summarizing Large Repositories

## Core Principle: Signal-to-Noise Optimization

**Goal:** Extract the 20% of code that explains 80% of the architecture.

---

## What to INCLUDE (High Signal)

### 1. **Entry Points** (Critical - Always Include)

```python
ALWAYS_INCLUDE = {
    # Files with main execution
    "files_with_main": ["__main__", "if __name__"],
    
    # Public API surfaces
    "api_endpoints": ["@app.route", "@api.route", "APIRouter", "FastAPI"],
    
    # CLI interfaces  
    "cli_commands": ["@click.command", "argparse", "typer"],
    
    # Worker/daemon processes
    "workers": ["celery.task", "rq.job", "worker.py", "daemon.py"],
    
    # Test entry points (for understanding usage)
    "test_fixtures": ["@pytest.fixture", "setUp", "TestCase"]
}
```

**Why:** These show *how* the system is used.

### 2. **Architectural Boundaries** (High Value)

```python
INCLUDE_BOUNDARIES = {
    # High in-degree = core utilities
    "hub_functions": "in_degree >= 10",
    
    # High out-degree = orchestrators
    "orchestrators": "out_degree >= 15",
    
    # High betweenness = bridges between subsystems
    "bridges": "top 10 by betweenness_centrality",
    
    # Foundation modules (imported by many)
    "core_modules": "imported by 5+ other modules"
}
```

**Extract:**
- Function signature
- First line of docstring only
- Parameter names (not types)
- Return type if annotated

### 3. **Public Interfaces** (API Surface)

```python
def is_public_interface(func_node: ast.FunctionDef, class_context: bool) -> bool:
    """Determine if function is part of public API."""
    
    # Explicit public markers
    if func_node.name.startswith("_"):
        return False  # private
    
    # Class methods
    if class_context:
        return func_node.name in ["__init__", "save", "delete", "get", "create"]
    
    # Top-level functions in __init__.py
    if in_init_file and not func_node.name.startswith("_"):
        return True
    
    # Decorated as API
    decorators = [d.id for d in func_node.decorator_list if isinstance(d, ast.Name)]
    if any(d in ["api", "route", "endpoint", "command"] for d in decorators):
        return True
    
    return False
```

**Extract:**
- Full signature with types
- Complete docstring
- Example usage from docstring
- Decorators

### 4. **Data Models** (Always Include)

```python
INCLUDE_MODELS = {
    # Dataclasses define data flow
    "dataclasses": "@dataclass",
    
    # Pydantic models define contracts
    "pydantic": "BaseModel subclasses",
    
    # SQLAlchemy defines data persistence
    "orm_models": "Base, Model subclasses",
    
    # Enums define constants
    "enums": "Enum subclasses",
    
    # TypedDict for typed structures
    "typed_dicts": "TypedDict subclasses"
}
```

**Extract:**
- Class name + bases
- All field names + types
- Class docstring
- Skip methods (usually CRUD, predictable)

### 5. **Configuration & Constants** (Context)

```python
INCLUDE_CONFIG = {
    # Module-level constants
    "constants": "UPPER_CASE variables at module level",
    
    # Config classes
    "settings": "Settings, Config classes",
    
    # Environment variables
    "env_vars": "os.getenv, os.environ calls"
}
```

**Extract:**
- Variable name + value (if literal)
- Comment above it

---

## What to EXCLUDE (Low Signal / Noise)

### 1. **Implementation Details** (Skip)

```python
ALWAYS_SKIP = {
    # Generated code
    "generated": ["# AUTO-GENERATED", "# Code generated", "DO NOT EDIT"],
    
    # Vendor/external code
    "vendor": ["vendor/", "third_party/", ".venv/", "site-packages/"],
    
    # Build artifacts
    "build": ["dist/", "build/", "*.egg-info/"],
    
    # Tests (unless entry points)
    "tests": ["test_*.py", "*_test.py", "tests/"],
    
    # Migrations (too granular)
    "migrations": ["migrations/", "alembic/versions/"],
    
    # Documentation
    "docs": ["docs/", "sphinx/"]
}
```

### 2. **Boilerplate Code** (Skip)

```python
def is_boilerplate(func: ast.FunctionDef) -> bool:
    """Identify low-information functions."""
    
    # Trivial getters/setters
    if func.name.startswith("get_") or func.name.startswith("set_"):
        if len(func.body) <= 2:  # just return or assignment
            return True
    
    # Property decorators (usually simple)
    if any(d.id == "property" for d in func.decorator_list):
        return True
    
    # __str__, __repr__ (predictable)
    if func.name in ["__str__", "__repr__", "__hash__", "__eq__"]:
        return True
    
    # Pass-through wrappers
    body = func.body
    if len(body) == 1 and isinstance(body[0], ast.Return):
        return True
    
    return False
```

### 3. **Helper/Utility Spam** (Selective)

```python
def should_include_utility(func_name: str, in_degree: int) -> bool:
    """Only include utilities that are widely used."""
    
    # Widely used utilities are important
    if in_degree >= 10:
        return True
    
    # Common patterns that don't add much
    noise_patterns = [
        "format_", "parse_", "convert_", "to_", "from_",
        "_helper", "_internal", "_util"
    ]
    
    if any(pattern in func_name for pattern in noise_patterns):
        if in_degree < 3:  # not widely used
            return False
    
    return True
```

### 4. **Verbose Docstrings** (Truncate)

```python
def extract_docstring(node: ast.FunctionDef) -> str:
    """Extract only the useful part of docstrings."""
    
    full_doc = ast.get_docstring(node) or ""
    
    # Skip empty or "TODO" only
    if not full_doc or full_doc.strip() in ["TODO", "TBD", "..."]:
        return ""
    
    # Split into sections
    lines = full_doc.split("\n")
    
    # Take only summary (first paragraph)
    summary = []
    for line in lines:
        if line.strip():
            summary.append(line.strip())
        else:
            break  # stop at first blank line
    
    result = " ".join(summary)
    
    # Truncate long docstrings
    if len(result) > 150:
        result = result[:147] + "..."
    
    return result
```

### 5. **Low-Importance Classes** (Skip)

```python
def should_skip_class(cls: ast.ClassDef, module_imports: int) -> bool:
    """Skip exception classes and simple containers."""
    
    # Exception classes (predictable structure)
    if any("Exception" in base or "Error" in base for base in cls.bases):
        return True
    
    # Classes with only __init__ and __str__
    method_names = [m.name for m in cls.body if isinstance(m, ast.FunctionDef)]
    if len(method_names) <= 2 and set(method_names) <= {"__init__", "__str__", "__repr__"}:
        return True
    
    # Classes in modules that are never imported
    if module_imports == 0:
        return True
    
    return False
```

---

## Prioritization Strategy

### Tier 1: Critical (Always in Summary)

```python
TIER_1_CRITERIA = {
    "entry_points": True,
    "public_api": True,
    "data_models": True,
    "graph_position": "in_degree >= 10 OR out_degree >= 15",
    "max_items": 50
}
```

**Extract:**
- Full signature
- Full docstring (first paragraph)
- All parameters
- Return type

### Tier 2: Important (Include if Space Allows)

```python
TIER_2_CRITERIA = {
    "graph_position": "5 <= in_degree < 10 OR 8 <= out_degree < 15",
    "bridges": "betweenness_centrality > 0.01",
    "core_utilities": "in_degree >= 5",
    "max_items": 100
}
```

**Extract:**
- Signature only (name + params)
- One-line docstring
- Skip parameter types

### Tier 3: Context (Include as File-Level Summary)

```python
TIER_3_CRITERIA = {
    "everything_else": True
}
```

**Extract:**
- File-level summary only: "Contains 15 functions for data validation"
- List of function names (no details)

---

## Token Budget Allocation

For a large repo, assume **~8000 tokens total** to LLM:

```python
TOKEN_BUDGET = {
    # High-level context
    "repo_stats": 200,           # files, lines, dependencies
    "graph_metrics": 300,         # centrality, depth, cycles
    "architecture_overview": 500, # from README
    
    # Detailed code analysis
    "tier_1_functions": 3000,     # ~50 functions × 60 tokens each
    "tier_2_functions": 2000,     # ~100 functions × 20 tokens each
    "tier_3_summaries": 1000,     # file-level summaries
    
    # Remaining for LLM reasoning
    "buffer": 1000
}
```

---

## Concrete Extraction Rules

### For Functions

```python
def extract_function_info(func: ast.FunctionDef, tier: int) -> dict:
    """Extract function info based on tier."""
    
    if tier == 1:
        return {
            "name": func.name,
            "signature": ast.unparse(func.args),
            "returns": ast.unparse(func.returns) if func.returns else None,
            "docstring": extract_docstring(func),
            "decorators": [ast.unparse(d) for d in func.decorator_list],
            "async": isinstance(func, ast.AsyncFunctionDef),
            "line_count": len(func.body)
        }
    
    elif tier == 2:
        return {
            "name": func.name,
            "params": [arg.arg for arg in func.args.args],
            "docstring": extract_docstring(func)[:50],  # truncated
        }
    
    else:  # tier 3
        return {
            "name": func.name
        }
```

### For Classes

```python
def extract_class_info(cls: ast.ClassDef, tier: int) -> dict:
    """Extract class info based on tier."""
    
    # Data models are always tier 1
    is_datamodel = any(
        base in ["BaseModel", "dataclass", "Base", "Model"]
        for base in [ast.unparse(b) for b in cls.bases]
    )
    
    if tier == 1 or is_datamodel:
        # Get all fields/attributes
        fields = []
        for node in cls.body:
            if isinstance(node, ast.AnnAssign):  # type-annotated attribute
                fields.append({
                    "name": node.target.id,
                    "type": ast.unparse(node.annotation)
                })
        
        return {
            "name": cls.name,
            "bases": [ast.unparse(b) for b in cls.bases],
            "docstring": extract_docstring(cls),
            "fields": fields,
            "methods": [m.name for m in cls.body if isinstance(m, ast.FunctionDef)],
            "is_datamodel": is_datamodel
        }
    
    else:
        return {
            "name": cls.name,
            "bases": [ast.unparse(b) for b in cls.bases]
        }
```

---

## Implementation: Prioritizer

```python
class CodePrioritizer:
    def __init__(self, call_graph: nx.DiGraph, import_graph: nx.DiGraph):
        self.call_graph = call_graph
        self.import_graph = import_graph
        
        # Compute metrics once
        self.in_degree = dict(call_graph.in_degree())
        self.out_degree = dict(call_graph.out_degree())
        self.betweenness = nx.betweenness_centrality(call_graph)
    
    def get_tier(self, func_id: str, is_entry_point: bool, is_public_api: bool) -> int:
        """Determine which tier a function belongs to."""
        
        # Tier 1: Critical
        if is_entry_point or is_public_api:
            return 1
        
        if self.in_degree.get(func_id, 0) >= 10:
            return 1
        
        if self.out_degree.get(func_id, 0) >= 15:
            return 1
        
        if self.betweenness.get(func_id, 0) > 0.05:
            return 1
        
        # Tier 2: Important
        if 5 <= self.in_degree.get(func_id, 0) < 10:
            return 2
        
        if 8 <= self.out_degree.get(func_id, 0) < 15:
            return 2
        
        # Tier 3: Context
        return 3
    
    def prioritize_functions(self, all_functions: List[str]) -> Dict[int, List[str]]:
        """Sort all functions into tiers."""
        
        tiers = {1: [], 2: [], 3: []}
        
        for func_id in all_functions:
            # Check if entry point or public API (you'd implement these checks)
            is_entry = self._is_entry_point(func_id)
            is_public = self._is_public_api(func_id)
            
            tier = self.get_tier(func_id, is_entry, is_public)
            tiers[tier].append(func_id)
        
        # Enforce limits
        tiers[1] = tiers[1][:50]   # max 50 tier-1 items
        tiers[2] = tiers[2][:100]  # max 100 tier-2 items
        
        return tiers
```

---

## Summary: Decision Matrix

| Element | Include? | Detail Level | Why |
|---------|----------|--------------|-----|
| **Entry points** | ✅ Always | Full | Shows how system is used |
| **Public API** | ✅ Always | Full | Defines contracts |
| **Data models** | ✅ Always | Full | Defines data flow |
| **Hub functions** (in-degree > 10) | ✅ Always | Full | Core utilities |
| **Orchestrators** (out-degree > 15) | ✅ Always | Full | System coordinators |
| **Bridge functions** (high betweenness) | ✅ Always | Medium | Connect subsystems |
| **Core utilities** (in-degree 5-10) | ⚠️ If space | Medium | Supporting functions |
| **Regular functions** | ⚠️ Summarize | Name only | Bulk of codebase |
| **Private helpers** (_prefixed) | ❌ Skip | None | Implementation details |
| **Getters/setters** | ❌ Skip | None | Trivial boilerplate |
| **Test code** | ❌ Skip* | None | *except entry fixtures |
| **Generated code** | ❌ Skip | None | Not authored code |
| **Migrations** | ❌ Skip | None | Too granular |
| **Exception classes** | ❌ Skip | None | Predictable structure |

---

## Validation: Are You Capturing Enough?

```python
def validate_coverage(tier_1_funcs: List[str], call_graph: nx.DiGraph) -> float:
    """Check if tier-1 functions cover most call paths."""
    
    tier_1_set = set(tier_1_funcs)
    
    # Count edges covered by tier-1 nodes
    covered_edges = 0
    total_edges = call_graph.number_of_edges()
    
    for u, v in call_graph.edges():
        if u in tier_1_set or v in tier_1_set:
            covered_edges += 1
    
    coverage = covered_edges / total_edges
    
    # Should be > 0.6 (tier-1 touches 60%+ of call graph)
    if coverage < 0.6:
        print(f"⚠️  Warning: Low coverage ({coverage:.1%}). Consider lowering thresholds.")
    
    return coverage
```

This strategy ensures you send the LLM **architectural signal, not implementation noise**.