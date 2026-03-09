import ast
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import networkx as nx

from src.llm.llm_adapter import summarize_with_llm
from src.utils import get_index, get_logger, get_path, short_doc

logger = get_logger(__name__)


@dataclass
class CallEdge:
    source: str
    target: str
    type: str  # "calls", "imports", "inherits"


@dataclass
class MethodInfo:
    name: str
    signature: str
    return_type: str
    docstring: str


@dataclass
class ClassInfo:
    name: str
    bases: List[str]
    methods: List[MethodInfo]
    docstring: str


@dataclass
class ModuleSkeleton:
    file: str
    module_name: str
    classes: List[ClassInfo]
    functions: List[str]
    imports_internal: List[str]
    imports_external: List[str]
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


def check_class_important(node: ast.ClassDef) -> bool:
    """Check if a class is important (should be included in skeleton).
    
    A class is considered important if:
    1. Its name doesn't start with underscore (public API)
    2. AND it meets at least one of:
       - Has a docstring (documented)
       - Has public methods
       - Has base classes (inheritance-based)
    
    This filters out empty/trivial classes and internal implementation details.
    """
    if node.name.startswith("_"):
        return False
    
    has_docstring = ast.get_docstring(node) is not None
    has_bases = len(node.bases) > 0
    
    public_methods = [
        item for item in node.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not item.name.startswith("_")
    ]
    
    return has_docstring or len(public_methods) > 0 or has_bases


def _is_boilerplate(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Identify low-information boilerplate functions.
    
    Boilerplate functions are those with little semantic value:
    - Simple getters/setters with minimal logic
    - Property decorators
    - Magic methods (__str__, __repr__, etc.)
    - Pass-through wrappers with single return
    """
    # Trivial getters/setters
    if func.name.startswith("get_") or func.name.startswith("set_"):
        if len(func.body) <= 2:  # just return or assignment
            return True
    
    # Property decorators (usually simple)
    if any(isinstance(d, ast.Name) and d.id == "property" for d in func.decorator_list):
        return True
    
    # __str__, __repr__ (predictable)
    if func.name in ["__str__", "__repr__", "__hash__", "__eq__", "__ne__", "__lt__", "__le__", "__gt__", "__ge__"]:
        return True
    
    # Pass-through wrappers - single return statement
    if len(func.body) == 1 and isinstance(func.body[0], ast.Return):
        return True
    
    return False


def check_function_important(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Check if a function is important (should be included in skeleton).
    
    A function is considered important if:
    1. Its name doesn't start with underscore (public API)
    2. AND it's not boilerplate code
    3. AND it meets at least one of:
       - Has a docstring (documented)
       - Has type annotations (typed API)
    
    This filters out private/internal functions, boilerplate code, and undocumented helpers.
    """
    if node.name.startswith("_"):
        return False
    
    if _is_boilerplate(node):
        return False
    
    has_docstring = ast.get_docstring(node) is not None
    has_annotations = node.returns is not None or any(arg.annotation for arg in node.args.args)
    
    return has_docstring or has_annotations


def _format_arguments(args: ast.arguments) -> str:
    parts: List[str] = []

    posonly = getattr(args, "posonlyargs", [])
    for arg in posonly:
        parts.append(arg.arg)
    if posonly:
        parts.append("/")

    for arg in args.args:
        parts.append(arg.arg)

    if args.vararg:
        parts.append("*" + args.vararg.arg)

    for arg in args.kwonlyargs:
        parts.append(arg.arg)

    if args.kwarg:
        parts.append("**" + args.kwarg.arg)

    return ", ".join(parts)


def _format_return_type(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    if node.returns is None:
        return ""
    return ast.unparse(node.returns)


def extract_classes(tree: ast.AST) -> List[ClassInfo]:
    """Extract class information from AST."""
    classes = []
    classes_candidates = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    for node in classes_candidates:
        if not check_class_important(node):
            logger.info(node.name)
            continue

        methods: List[MethodInfo] = []
        for method_node in node.body:
            if not isinstance(method_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            signature = _format_arguments(method_node.args)
            return_type = _format_return_type(method_node)
            methods.append(
                MethodInfo(
                    name=method_node.name,
                    signature=signature,
                    return_type=return_type,
                    docstring=short_doc(method_node),
                )
            )

        bases = [ast.unparse(b) for b in node.bases]
        docstring = short_doc(node, max_len=150)

        classes.append(ClassInfo(name=node.name, bases=bases, methods=methods, docstring=docstring))

    return classes


def extract_functions(tree: ast.AST) -> List[str]:
    """Extract top-level function names from AST."""
    functions = []
    
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        
        if node.col_offset != 0:
            continue

        if not check_function_important(node):
            logger.info(node.name)
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

    return ModuleSkeleton(
        file=str(py_file.relative_to(repo_root)),
        module_name=module_name,
        classes=classes,
        functions=functions,
        imports_internal=internal,
        imports_external=external,
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
                        logger.info(node.name)
                        continue
                    if not check_function_important(method):
                        logger.info(method.name)
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
                logger.info(node.name)
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
    rel = py_file.relative_to(repo_root)
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


def build_call_graph(edges: List[CallEdge]) -> nx.DiGraph:
    graph = nx.DiGraph()
    for edge in edges:
        if edge.type == "calls":
            graph.add_edge(edge.source, edge.target)
    return graph


def build_import_graph(skeletons: List[ModuleSkeleton]) -> nx.DiGraph:
    graph = nx.DiGraph()
    for skeleton in skeletons:
        for dep in skeleton.imports_internal:
            graph.add_edge(skeleton.module_name, dep)
    return graph


def analyze_call_graph(graph: nx.DiGraph) -> GraphAnalysis:
    if graph.number_of_nodes() == 0:
        return GraphAnalysis([], [], [], 0, 0, 0)

    in_deg = dict(graph.in_degree())
    out_deg = dict(graph.out_degree())

    utilities = [n for n in graph.nodes() if in_deg[n] > 5 and out_deg[n] < 3]
    orchestrators = [n for n in graph.nodes() if out_deg[n] > 10]
    most_called = sorted(in_deg, key=in_deg.get, reverse=True)[:10]

    try:
        cycles = list(nx.simple_cycles(graph))
    except Exception:
        cycles = []

    try:
        max_depth = nx.dag_longest_path_length(graph)
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


def analyze_repository(repo_path: str, api_key: Optional[str] = None) -> Tuple[RepoSummary, nx.DiGraph, nx.DiGraph]:
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

    print("Step 2: Building call and import graphs...")
    call_graph = build_call_graph(call_edges)
    import_graph = build_import_graph(skeletons)

    print(f"Call graph: {call_graph.number_of_nodes()} nodes, {call_graph.number_of_edges()} edges")
    print(f"Import graph: {import_graph.number_of_nodes()} nodes, {import_graph.number_of_edges()} edges")

    print("Step 3: Analyzing call graph...")
    graph_analysis = analyze_call_graph(call_graph)

    print("Step 4: Computing statistics...")
    total_lines = sum(s.line_count for s in skeletons)
    total_functions = sum(len(s.functions) for s in skeletons)
    total_classes = sum(len(s.classes) for s in skeletons)

    all_external = [dep for s in skeletons for dep in s.imports_external]
    dep_counts = Counter(all_external)
    top_deps = [dep for dep, _ in dep_counts.most_common(20)]
    entry_points = find_entry_points(repo_root)

    print("Step 5: Generating LLM summary...")
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


def export_graph(call_graph: nx.DiGraph, import_graph: nx.DiGraph, output_path: Path) -> None:
    """Export graphs with full edge metadata (source, target, type)."""
    def _graph_to_dict(graph: nx.DiGraph, edge_type: str) -> dict:
        """Convert NetworkX graph to dict with nodes and typed edges."""
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