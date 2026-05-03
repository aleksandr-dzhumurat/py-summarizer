import ast
import hashlib
import json
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Set, Tuple

from src.llm.llm_adapter import summarize_with_llm
from .naive_skeleton import check_class_important, check_function_important, extract_classes, ClassInfo, MethodInfo
from .utils import get_index, get_logger, get_path

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Graph node
# ---------------------------------------------------------------------------

@dataclass
class CodeGraphNode:
    name: str


# ---------------------------------------------------------------------------
# Directed graph
# ---------------------------------------------------------------------------

def _make_node(name: str) -> CodeGraphNode:
    return CodeGraphNode(name=name)


def _key(name: str) -> str:
    return hashlib.md5(name.encode()).hexdigest()


class DiGraph:
    def __init__(self) -> None:
        self._nodes: Dict[str, CodeGraphNode] = {}
        self._succ: Dict[str, Set[str]] = defaultdict(set)
        self._pred: Dict[str, Set[str]] = defaultdict(set)

    def _register(self, name: str) -> str:
        k = _key(name)
        if k not in self._nodes:
            self._nodes[k] = _make_node(name)
        return k

    def add_edge(self, source: str, target: str) -> None:
        src = self._register(source)
        tgt = self._register(target)
        self._succ[src].add(tgt)
        self._pred[tgt].add(src)

    def number_of_nodes(self) -> int:
        return len(self._nodes)

    def number_of_edges(self) -> int:
        return sum(len(s) for s in self._succ.values())

    def nodes(self) -> List[str]:
        return [n.name for n in self._nodes.values()]

    def edges(self) -> Iterator[Tuple[str, str]]:
        for src_key, tgt_keys in self._succ.items():
            src = self._nodes[src_key].name
            for tgt_key in tgt_keys:
                yield src, self._nodes[tgt_key].name

    def in_degree(self) -> Dict[str, int]:
        return {n.name: len(self._pred.get(k, set())) for k, n in self._nodes.items()}

    def out_degree(self) -> Dict[str, int]:
        return {n.name: len(self._succ.get(k, set())) for k, n in self._nodes.items()}

    def successors(self, name: str) -> Set[str]:
        return {self._nodes[k].name for k in self._succ.get(_key(name), set())}


def simple_cycles(graph: DiGraph) -> List[List[str]]:
    """Find cycles via DFS back-edge detection."""
    cycles: List[List[str]] = []
    color: Dict[str, int] = {}
    path: List[str] = []

    def _dfs(node: str) -> None:
        color[node] = 1
        path.append(node)
        for nb in graph.successors(node):
            if color.get(nb) == 1:
                cycles.append(path[path.index(nb):])
            elif not color.get(nb):
                _dfs(nb)
        path.pop()
        color[node] = 2

    for node in graph.nodes():
        if not color.get(node):
            _dfs(node)

    return cycles


def dag_longest_path_length(graph: DiGraph) -> int:
    """Longest path in a DAG via Kahn's topological sort + DP."""
    remaining = dict(graph.in_degree())
    queue: deque = deque(n for n, d in remaining.items() if d == 0)
    topo: List[str] = []

    while queue:
        node = queue.popleft()
        topo.append(node)
        for nb in graph.successors(node):
            remaining[nb] -= 1
            if remaining[nb] == 0:
                queue.append(nb)

    if len(topo) != graph.number_of_nodes():
        raise ValueError("Graph contains cycles — not a DAG")

    dist: Dict[str, int] = {n: 0 for n in graph.nodes()}
    for node in topo:
        for nb in graph.successors(node):
            if dist[node] + 1 > dist[nb]:
                dist[nb] = dist[node] + 1

    return max(dist.values()) if dist else 0


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CallEdge:
    source: str
    target: str
    type: str  # "calls", "imports", "inherits"


@dataclass
class ModuleSkeleton:
    file: str
    module_name: str
    classes: List[ClassInfo]
    functions: List[str]
    imports_internal: List[str]
    imports_external: List[str]
    name_imports: Dict[str, str]  # local_name -> source_module (from-import resolution)
    line_count: int


@dataclass
class GraphAnalysis:
    most_called: List[str]
    utilities: List[str]
    orchestrators: List[str]
    max_call_depth: int
    circular_dependencies: int
    total_functions: int


@dataclass
class RepoSummary:
    repo_path: str
    total_files: int
    total_lines: int
    total_functions: int
    total_classes: int
    entry_points: List[str]
    external_dependencies: List[str]
    graph_analysis: GraphAnalysis
    summary: str


def extract_functions(tree: ast.AST) -> List[str]:
    """Extract top-level function names from AST."""
    functions = []
    
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        
        if node.col_offset != 0:
            continue

        if not check_function_important(node):
            logger.debug(node.name)
            continue

        functions.append(node.name)
    
    return functions


def extract_file(py_file: Path, repo_root: Path) -> Optional[ModuleSkeleton]:
    try:
        source = py_file.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source)
    except Exception:
        return None

    module_name = _path_to_module(py_file, repo_root)
    
    classes = extract_classes(tree)
    functions = extract_functions(tree)
    internal, external = _extract_imports(tree, repo_root)
    name_imports = _extract_name_imports(tree, repo_root)

    return ModuleSkeleton(
        file=str(py_file.resolve().relative_to(repo_root)),
        module_name=module_name,
        classes=classes,
        functions=functions,
        imports_internal=internal,
        imports_external=external,
        name_imports=name_imports,
        line_count=source.count("\n"),
    )


def extract_call_edges(py_file: Path, repo_root: Path) -> List[CallEdge]:
    try:
        source = py_file.read_text(errors="ignore")
        tree = ast.parse(source)
    except Exception:
        return []

    module_name = _path_to_module(py_file, repo_root)
    edges = []
    stdlib = __import__("sys").stdlib_module_names
    # Python builtin types and functions
    builtins = {
        "str", "int", "float", "bool", "list", "dict", "set", "tuple",
        "bytes", "bytearray", "complex", "frozenset", "type", "object",
        "len", "range", "sum", "map", "filter", "zip", "enumerate",
        "sorted", "reversed", "min", "max", "abs", "round", "pow",
        "print", "input", "open", "iter", "next", "callable", "repr",
        "format", "hash", "id", "isinstance", "issubclass", "hasattr",
        "getattr", "setattr", "delattr", "dir", "vars", "globals",
        "locals", "eval", "exec", "compile", "super", "property",
        "classmethod", "staticmethod", "Exception", "BaseException",
    }

    important_class_names = {class_info.name for class_info in extract_classes(tree)}
    parent_map: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parent_map[child] = parent

    def _is_stdlib_call(callee: str) -> bool:
        """Check if a callee is from the standard library or builtins."""
        # Handle format: "module.method" or "method"
        top_level = callee.split(".")[0]
        return top_level in stdlib or top_level in builtins

    def _is_generic_data_method(callee: str) -> bool:
        """Check if a callee is a generic data structure method (low information value).
        
        These are common methods on dictionaries, lists, and other objects that don't
        provide semantic insight into the code's intent.
        """
        # Common low-value dict/list methods
        generic_methods = {
            "get", "append", "extend", "pop", "remove", "clear", "update",
            "items", "keys", "values", "join", "split", "strip", "replace",
            "startswith", "endswith", "lower", "upper", "capitalize",
            "copy", "add", "discard", "difference", "union", "intersection",
            "model_dump", "model_copy", "model_validate", "model_validate_json",
            "read", "write", "open", "close",
        }
        # Check if the last part (method name) is a generic method
        method_name = callee.split(".")[-1]
        return method_name in generic_methods

    def _is_private_function(callee: str) -> bool:
        """Check if a callee is a private function (any segment starts with underscore)."""
        # Split by dots and check if any segment is private (starts with underscore)
        # e.g., "_get_state_dict" or "Runner._get_or_create_session" 
        segments = callee.split(".")
        return any(seg.startswith("_") for seg in segments)

    def _is_logging_call(callee: str) -> bool:
        """Check if a callee is a logging call (logger.*, logging.*)."""
        parts = callee.split(".")
        logging_methods = {"debug", "info", "warning", "error", "critical", "exception"}
        
        # Check if the last part is a logging method
        if len(parts) >= 2 and parts[-1] in logging_methods:
            # Check if any part contains "logger" or if it starts with "logging"
            if any("logger" in part for part in parts[:-1]) or parts[0] == "logging":
                return True
        return False

    def _is_exception_class(callee: str) -> bool:
        """Check if a callee is an exception or error class."""
        exception_classes = {
            "ValueError", "TypeError", "KeyError", "AttributeError",
            "RuntimeError", "NotImplementedError", "OSError", "IOError",
            "ImportError", "ModuleNotFoundError", "FileNotFoundError",
            "ConnectionError", "TimeoutError", "NameError", "IndexError",
            "Exception", "BaseException", "StopIteration", "GeneratorExit",
            "SystemExit", "KeyboardInterrupt", "AssertionError", "SyntaxError",
            "IndentationError", "TabError", "SystemError", "ReferenceError",
            "MemoryError", "BufferError", "Warning", "DeprecationWarning",
            "PendingDeprecationWarning", "RuntimeWarning", "SyntaxWarning",
            "UserWarning", "FutureWarning", "ImportWarning", "UnicodeWarning",
            "BytesWarning", "ResourceWarning", "EnvironmentError", "HTTPError",
            "URLError", "NotFoundError", "AlreadyExistsError", "ClickException",
            "BadParameter", "UsageError", "Abort", "ReplayConfigError",
        }
        # Get the last part (class name)
        class_name = callee.split(".")[-1]
        return class_name in exception_classes

    # Get top-level functions (module-level and class methods, but not nested functions)
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for method in node.body:
                if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name not in important_class_names:
                        logger.debug(node.name)
                        continue
                    if not check_function_important(method):
                        logger.debug(method.name)
                        continue
                    
                    caller = f"{module_name}.{method.name}"
                    class_name = node.name
                    
                    for call_node in ast.walk(method):
                        if isinstance(call_node, ast.Call):
                            callee = _get_call_name(call_node, class_name)
                            if callee and not _is_stdlib_call(callee) and not _is_generic_data_method(callee) and not _is_private_function(callee) and not _is_logging_call(callee) and not _is_exception_class(callee):
                                edges.append(CallEdge(caller, callee, "calls"))
        
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not check_function_important(node):
                logger.debug(node.name)
                continue
            
            caller = f"{module_name}.{node.name}"
            
            for call_node in ast.walk(node):
                if isinstance(call_node, ast.Call):
                    callee = _get_call_name(call_node)
                    if callee and not _is_stdlib_call(callee) and not _is_generic_data_method(callee) and not _is_private_function(callee) and not _is_logging_call(callee) and not _is_exception_class(callee):
                        edges.append(CallEdge(caller, callee, "calls"))

    return edges

def _extract_imports(tree: ast.AST, repo_root: Path) -> Tuple[List[str], List[str]]:
    internal, external = [], []
    stdlib = __import__("sys").stdlib_module_names

    for node in ast.walk(tree):
        module = None
        if isinstance(node, ast.ImportFrom) and node.module:
            module = node.module
        elif isinstance(node, ast.Import):
            module = node.names[0].name

        if not module:
            continue

        root_pkg = module.split(".")[0]
        if root_pkg in stdlib:
            continue

        candidate = repo_root / module.replace(".", "/")
        if candidate.with_suffix(".py").exists() or (candidate / "__init__.py").exists():
            internal.append(module)
        else:
            external.append(root_pkg)

    return list(set(internal)), list(set(external))


def _extract_name_imports(tree: ast.AST, repo_root: Path) -> Dict[str, str]:
    """Return {local_name: source_module} for internal from-imports.

    Covers `from src.foo import Bar, baz` → {"Bar": "src.foo", "baz": "src.foo"}.
    Star imports and stdlib/external imports are skipped.
    """
    stdlib = __import__("sys").stdlib_module_names
    result: Dict[str, str] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ImportFrom) and node.module):
            continue
        root_pkg = node.module.split(".")[0]
        if root_pkg in stdlib:
            continue
        candidate = repo_root / node.module.replace(".", "/")
        if not (candidate.with_suffix(".py").exists() or (candidate / "__init__.py").exists()):
            continue
        for alias in node.names:
            if alias.name == "*":
                continue
            local_name = alias.asname or alias.name
            result[local_name] = node.module
    return result


def _expr_to_name(expr: ast.AST, class_name: Optional[str] = None) -> Optional[str]:
    if isinstance(expr, ast.Name):
        # Replace "self" with actual class name if provided
        if expr.id == "self" and class_name:
            return class_name
        return expr.id
    if isinstance(expr, ast.Attribute):
        base = _expr_to_name(expr.value, class_name)
        return f"{base}.{expr.attr}" if base else expr.attr
    if isinstance(expr, ast.Subscript):
        return _expr_to_name(expr.value, class_name)
    if isinstance(expr, ast.Call):
        return _expr_to_name(expr.func, class_name)
    return None


def _get_call_name(node: ast.Call, class_name: Optional[str] = None) -> Optional[str]:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        base = _expr_to_name(node.func.value, class_name)
        return f"{base}.{node.func.attr}" if base else node.func.attr
    return None


def _path_to_module(py_file: Path, repo_root: Path) -> str:
    rel = py_file.resolve().relative_to(repo_root)
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1].removesuffix(".py")
    return ".".join(parts) if parts else "root"


def find_entry_points(repo_root: Path) -> List[str]:
    entries = []
    for py_file in repo_root.rglob("*.py"):
        try:
            source = py_file.read_text(errors="ignore")
            if '__name__ == "__main__"' in source:
                entries.append(str(py_file.relative_to(repo_root)))
        except Exception:
            pass
    return entries


def extract_inheritance_edges(skeletons: List[ModuleSkeleton]) -> List[CallEdge]:
    """Emit one CallEdge(type='inherits') per base class per class in each skeleton."""
    edges = []
    for sk in skeletons:
        for cls in sk.classes:
            for base in cls.bases:
                edges.append(CallEdge(f"{sk.module_name}.{cls.name}", base, "inherits"))
    return edges


def build_call_graph(edges: List[CallEdge]) -> DiGraph:
    graph = DiGraph()
    for edge in edges:
        if edge.type in ("calls", "inherits"):
            graph.add_edge(edge.source, edge.target)
    return graph


def resolve_call_edges(edges: List[CallEdge], skeletons: List[ModuleSkeleton]) -> List[CallEdge]:
    """Rewrite unqualified callee names to fully-qualified module.name targets.

    For each call edge where the callee is a bare name (e.g. "get_subgraph"),
    look up the caller module's from-import map. If the name was imported from
    an internal module N, rewrite the target to "N.get_subgraph".

    Example:
        src.app imports `from src.retrieval import get_subgraph`
        edge (src.app.endpoint, "get_subgraph") → (src.app.endpoint, "src.retrieval.get_subgraph")
    """
    name_imports: Dict[str, Dict[str, str]] = {sk.module_name: sk.name_imports for sk in skeletons}

    resolved = []
    for edge in edges:
        if edge.type != "calls":
            resolved.append(edge)
            continue
        caller_module = edge.source.rsplit(".", 1)[0]
        imports = name_imports.get(caller_module, {})
        base = edge.target.split(".")[0]
        if base in imports:
            resolved.append(CallEdge(edge.source, f"{imports[base]}.{edge.target}", edge.type))
        else:
            resolved.append(edge)
    return resolved


def build_import_graph(skeletons: List[ModuleSkeleton]) -> DiGraph:
    graph = DiGraph()
    for skeleton in skeletons:
        for dep in skeleton.imports_internal:
            graph.add_edge(skeleton.module_name, dep)
    return graph


def analyze_call_graph(graph: DiGraph) -> GraphAnalysis:
    if graph.number_of_nodes() == 0:
        return GraphAnalysis([], [], [], 0, 0, 0)

    in_deg = dict(graph.in_degree())
    out_deg = dict(graph.out_degree())

    utilities = [n for n in graph.nodes() if in_deg[n] > 5 and out_deg[n] < 3]
    orchestrators = [n for n in graph.nodes() if out_deg[n] > 10]
    most_called = sorted(in_deg, key=in_deg.get, reverse=True)[:10]

    try:
        cycles = list(simple_cycles(graph))
    except Exception:
        cycles = []

    try:
        max_depth = dag_longest_path_length(graph)
    except Exception:
        max_depth = -1

    return GraphAnalysis(
        most_called=most_called,
        utilities=utilities[:10],
        orchestrators=orchestrators[:10],
        max_call_depth=max_depth,
        circular_dependencies=len(cycles),
        total_functions=graph.number_of_nodes(),
    )


def analyze_repository(repo_path: str, api_key: Optional[str] = None) -> Tuple[RepoSummary, DiGraph, DiGraph]:
    repo_root = Path(repo_path).resolve()

    if not repo_root.exists():
        raise ValueError(f"Path does not exist: {repo_path}")

    print(f"Analyzing repository: {repo_root}")
    print("Step 1: Extracting AST from Python files...")
    skeletons = []
    call_edges = []

    repo_index = get_index(str(repo_root))
    print(f"Found {len(repo_index)} files in index")

    for entry in repo_index:
        file_path = get_path(entry, str(repo_root))
        if not file_path:
            continue

        if not str(file_path).endswith(".py"):
            continue

        skeleton = extract_file(file_path, repo_root)
        if skeleton:
            skeletons.append(skeleton)

        edges = extract_call_edges(file_path, repo_root)
        call_edges.extend(edges)

    print(f"Extracted {len(skeletons)} modules, {len(call_edges)} call edges")

    print("Step 2: Resolving call edge targets...")
    resolved_edges = resolve_call_edges(call_edges, skeletons)
    resolved_count = sum(1 for a, b in zip(call_edges, resolved_edges) if a.target != b.target)
    print(f"Resolved {resolved_count}/{len(call_edges)} edges to fully-qualified targets")

    inheritance_edges = extract_inheritance_edges(skeletons)
    print(f"Extracted {len(inheritance_edges)} inheritance edges")

    print("Step 3: Building call and import graphs...")
    call_graph = build_call_graph(resolved_edges + inheritance_edges)
    import_graph = build_import_graph(skeletons)

    print(f"Call graph: {call_graph.number_of_nodes()} nodes, {call_graph.number_of_edges()} edges")
    print(f"Import graph: {import_graph.number_of_nodes()} nodes, {import_graph.number_of_edges()} edges")

    print("Step 4: Analyzing call graph...")
    graph_analysis = analyze_call_graph(call_graph)

    print("Step 5: Computing statistics...")
    total_lines = sum(s.line_count for s in skeletons)
    total_functions = sum(len(s.functions) for s in skeletons)
    total_classes = sum(len(s.classes) for s in skeletons)

    all_external = [dep for s in skeletons for dep in s.imports_external]
    dep_counts = Counter(all_external)
    top_deps = [dep for dep, _ in dep_counts.most_common(20)]
    entry_points = find_entry_points(repo_root)

    print("Step 6: Generating LLM summary...")
    summary = summarize_with_llm(skeletons, graph_analysis, top_deps, entry_points, api_key)

    repo_summary = RepoSummary(
        repo_path=str(repo_root),
        total_files=len(skeletons),
        total_lines=total_lines,
        total_functions=total_functions,
        total_classes=total_classes,
        entry_points=entry_points,
        external_dependencies=top_deps,
        graph_analysis=graph_analysis,
        summary=summary,
    )
    
    return repo_summary, call_graph, import_graph


def export_json(summary: RepoSummary, output_path: Path) -> None:
    data = {
        "repo_path": summary.repo_path,
        "stats": {
            "files": summary.total_files,
            "lines": summary.total_lines,
            "functions": summary.total_functions,
            "classes": summary.total_classes,
        },
        "entry_points": summary.entry_points,
        "dependencies": summary.external_dependencies,
        "graph_analysis": {
            "most_called": summary.graph_analysis.most_called,
            "utilities": summary.graph_analysis.utilities,
            "orchestrators": summary.graph_analysis.orchestrators,
            "max_call_depth": summary.graph_analysis.max_call_depth,
            "circular_dependencies": summary.graph_analysis.circular_dependencies,
        },
        "summary": summary.summary,
    }

    with open(output_path, "w", encoding="utf-8") as file_obj:
        json.dump(data, file_obj, indent=2)

    print(f"Exported JSON to: {output_path}")


def export_markdown(summary: RepoSummary, output_path: Path) -> None:
    markdown_text = f"""# Repository Analysis

## Summary

{summary.summary}

## Statistics

- **Files:** {summary.total_files}
- **Lines of Code:** {summary.total_lines:,}
- **Functions:** {summary.total_functions}
- **Classes:** {summary.total_classes}

## Entry Points

{chr(10).join(f'- `{ep}`' for ep in summary.entry_points) if summary.entry_points else '- None found'}

## Call Graph Analysis

### Most Called Functions
{chr(10).join(f'- `{func}`' for func in summary.graph_analysis.most_called[:10])}

### Utility Functions (called by many, call few)
{chr(10).join(f'- `{func}`' for func in summary.graph_analysis.utilities[:5]) if summary.graph_analysis.utilities else '- None identified'}

### Orchestrator Functions (call many others)
{chr(10).join(f'- `{func}`' for func in summary.graph_analysis.orchestrators[:5]) if summary.graph_analysis.orchestrators else '- None identified'}

### Complexity Metrics
- **Max Call Depth:** {summary.graph_analysis.max_call_depth}
- **Circular Dependencies:** {summary.graph_analysis.circular_dependencies}
- **Total Functions in Graph:** {summary.graph_analysis.total_functions}
"""

    with open(output_path, "w", encoding="utf-8") as file_obj:
        file_obj.write(markdown_text)

    print(f"Exported Markdown to: {output_path}")


def export_graph(call_graph: DiGraph, import_graph: DiGraph, output_path: Path) -> None:
    """Export graphs with full edge metadata (source, target, type)."""
    def _graph_to_dict(graph: DiGraph, edge_type: str) -> dict:
        edges = []
        for source, target in graph.edges():
            edges.append({
                "source": source,
                "target": target,
                "type": edge_type,
            })
        
        return {
            "nodes": list(graph.nodes()),
            "edges": edges,
        }
    
    data = {
        "call_graph": _graph_to_dict(call_graph, "calls"),
        "import_graph": _graph_to_dict(import_graph, "imports"),
    }

    with open(output_path, "w", encoding="utf-8") as file_obj:
        json.dump(data, file_obj, indent=2)

    print(f"Exported graphs to: {output_path}")


__all__ = [
    "CallEdge",
    "MethodInfo",
    "ClassInfo",
    "ModuleSkeleton",
    "GraphAnalysis",
    "RepoSummary",
    "check_class_important",
    "check_function_important",
    "analyze_repository",
    "export_json",
    "export_markdown",
    "export_graph",
]