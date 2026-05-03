"""Generate a naive code skeleton from an index of files.

Function `code_skeleton(index: list)` reads .py files from the provided
index (list of dicts with key `file_path`) and returns a string that
contains the imports found in each file (excluding standard library)
and a list of functions defined there (with parameter lists and docstrings).
Class methods are reported as `ClassName.method`.

Files or functions whose names start with `_` are skipped.
"""

import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Set

try:
    from .utils import (
        clean_markdown_text,
        get_absolute_imports_flag,
        get_class_definitions_flag,
        get_class_methods_flag,
        get_functions_flag,
        get_index,
        get_logger,
        get_path,
        get_relative_imports_flag,
        short_doc,
    )
except ImportError:
    from utils import (  # type: ignore[no-redef]
        clean_markdown_text,
        get_absolute_imports_flag,
        get_class_definitions_flag,
        get_class_methods_flag,
        get_functions_flag,
        get_index,
        get_logger,
        get_path,
        get_relative_imports_flag,
        short_doc,
    )

logger = get_logger(__name__)

# Cache stdlib modules once at module load time (Python 3.10+)
STDLIB_MODULES: Set[str] = sys.stdlib_module_names

# Part type constants - Simple is better than complex
PART_IMPORT_REL = "import_relative"
PART_IMPORT_ABS = "import_absolute"
PART_DOCSTRING = "docstring"
PART_FUNCTION = "function"
PART_CLASS = "class"


@dataclass
class Part:
    type: str  # PART_* constant
    text: str


@dataclass
class SkeletonEntry:
    source: str
    file_type: str  # 'doc' or 'code'
    content: List[Part]


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


def check_class_important(node: ast.ClassDef) -> bool:
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
    if func.name.startswith("get_") or func.name.startswith("set_"):
        if len(func.body) <= 2:
            return True
    if any(isinstance(d, ast.Name) and d.id == "property" for d in func.decorator_list):
        return True
    if func.name in ["__str__", "__repr__", "__hash__", "__eq__", "__ne__", "__lt__", "__le__", "__gt__", "__ge__"]:
        return True
    if len(func.body) == 1 and isinstance(func.body[0], ast.Return):
        return True
    return False


def check_function_important(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    if node.name.startswith("_"):
        return False
    if _is_boilerplate(node):
        return False
    has_docstring = ast.get_docstring(node) is not None
    has_annotations = node.returns is not None or any(arg.annotation for arg in node.args.args)
    return has_docstring or has_annotations


def extract_classes(tree: ast.AST) -> List[ClassInfo]:
    """Extract class information from AST."""
    classes = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if not check_class_important(node):
            continue
        methods: List[MethodInfo] = []
        for method_node in node.body:
            if not isinstance(method_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            signature = _format_arguments(method_node.args)
            return_type = ast.unparse(method_node.returns) if method_node.returns else ""
            methods.append(MethodInfo(
                name=method_node.name,
                signature=signature,
                return_type=return_type,
                docstring=short_doc(method_node),
            ))
        bases = [ast.unparse(b) for b in node.bases]
        classes.append(ClassInfo(name=node.name, bases=bases, methods=methods, docstring=short_doc(node, max_len=150)))
    return classes


def _format_arguments(args: ast.arguments) -> str:
    parts: List[str] = []

    def _arg_name(a: ast.arg) -> str:
        return a.arg

    # positional-only (Python 3.8+)
    posonly = getattr(args, "posonlyargs", [])
    for a in posonly:
        parts.append(_arg_name(a))
    if posonly:
        parts.append("/")

    # regular args
    for a in args.args:
        parts.append(_arg_name(a))

    # vararg
    if args.vararg:
        parts.append("*" + _arg_name(args.vararg))

    # keyword-only args
    for a in args.kwonlyargs:
        parts.append(_arg_name(a))

    # kwarg
    if args.kwarg:
        parts.append("**" + _arg_name(args.kwarg))

    # Note: defaults and annotations are omitted for brevity; names are primary
    return ", ".join(parts)


def _is_stdlib_module(module_name: str) -> bool:
    """Check if a module name is from the Python standard library."""
    top_level = module_name.split(".")[0]
    return top_level in STDLIB_MODULES


def _collect_imports(tree: ast.AST) -> dict:
    """Return dict with 'relative' and 'absolute' import lists."""
    rel_imports: List[str] = []
    abs_imports: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                if _is_stdlib_module(n.name):
                    continue
                if n.asname:
                    abs_imports.append(f"import {n.name} as {n.asname}")
                else:
                    abs_imports.append(f"import {n.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if _is_stdlib_module(module):
                continue
            names = ", ".join([f"{n.name}" + (f" as {n.asname}" if n.asname else "") for n in node.names])
            level = getattr(node, "level", 0)
            if level > 0:
                rel_imports.append(f"from {'.'*level}{module} import {names}")
            else:
                abs_imports.append(f"from {module} import {names}")
    return {"relative": rel_imports, "absolute": abs_imports}


def _extract_module_docstring(tree: ast.AST) -> Part | None:
    """Extract module-level docstring as a Part."""
    doc = ast.get_docstring(tree)
    if not doc:
        return None
    # Convert multi-line docstring to single line by replacing newlines with '. '
    single_line = doc.strip().replace('\n', '. ').replace('  ', ' ')
    text = f"{single_line[:197]}..." if len(single_line) > 200 else single_line
    return Part(type=PART_DOCSTRING, text=text)


def _extract_imports(tree: ast.AST) -> List[Part]:
    """Extract import statements as Parts."""
    imports = _collect_imports(tree)
    parts: List[Part] = []
    for im in sorted(set(imports["relative"])):
        parts.append(Part(type=PART_IMPORT_REL, text=im))
    for im in sorted(set(imports["absolute"])):
        parts.append(Part(type=PART_IMPORT_ABS, text=im))
    return parts


def _extract_functions(tree: ast.AST) -> List[Part]:
    """Extract top-level functions as Parts."""
    parts: List[Part] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if check_function_important(node):
                sig = _format_arguments(node.args)
                return_type = ast.unparse(node.returns) if node.returns else ""
                doc = short_doc(node)
                
                func_text = f"{node.name}({sig})"
                if return_type:
                    func_text += f" -> {return_type}"
                if doc:
                    func_text += f" | {doc}"
                parts.append(Part(type=PART_FUNCTION, text=func_text))
    return parts


def _extract_classes(tree: ast.AST) -> List[Part]:
    """Extract class definitions (including nested) and their methods as Parts."""
    parts: List[Part] = []
    classes_info = extract_classes(tree)

    for class_info in classes_info:
        cls_text = f"{class_info.name}: {class_info.docstring}" if class_info.docstring else class_info.name
        parts.append(Part(type=PART_CLASS, text=cls_text))

        for method in class_info.methods:
            if method.name.startswith("_"):
                continue

            method_text = f"{class_info.name}.{method.name}({method.signature})"
            if method.return_type:
                method_text += f" -> {method.return_type}"
            if method.docstring:
                method_text += f" | {method.docstring}"
            parts.append(Part(type=PART_FUNCTION, text=method_text))

    return parts


def process_code(file_path: Path) -> List[SkeletonEntry]:
    """Process a single Python file and extract its structure.
    
    Args:
        file_path: Resolved Path object to the file
        
    Returns:
        List of SkeletonEntry for this file
    """
    try:
        src = file_path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(src)
    except Exception as e:
        logger.warning(f"Failed to parse {file_path}: {e}")
        return []
    
    content: List[Part] = []

    if doc_part := _extract_module_docstring(tree):
        content.append(doc_part)
    
    content.extend(_extract_imports(tree))
    content.extend(_extract_functions(tree))
    content.extend(_extract_classes(tree))

    return [SkeletonEntry(source=str(file_path), file_type="code", content=content)]


def process_doc(file_path: Path) -> List[SkeletonEntry]:
    """Process a single documentation file (.md, .rst, .txt).
    
    Args:
        file_path: Resolved Path object to the file
        
    Returns:
        List of SkeletonEntry for this file
    """
    p = Path(file_path)
    if p.name.upper().startswith(('LICENSE', 'SKELETON', 'CODEOWNERS', 'SECURITY', 'REQUIREMENTS')):
        return []
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        cleaned = clean_markdown_text(content)
        
        if not cleaned:
            return [SkeletonEntry(source=str(file_path), file_type="doc", content=[])]
        
        # Convert multi-line docstring to single line by replacing newlines with '. '
        cleaned_single_line = cleaned.replace('\n', '. ').replace('  ', ' ').strip()
        preview = cleaned_single_line[:500] + "..." if len(cleaned_single_line) > 500 else cleaned_single_line
        return [SkeletonEntry(source=str(file_path), file_type="doc", content=[Part(type=PART_DOCSTRING, text=preview)])]
    except Exception as e:
        logger.warning(f"Failed to read {file_path}: {e}")
        return []


def import_summarize(import_parts: List[Part]) -> str:
    packages: set[str] = set()
    for part in import_parts:
        text = part.text.strip()
        if text.startswith("import "):
            name = text[len("import "):].split(" as ")[0].strip()
        elif text.startswith("from "):
            name = text[len("from "):].split(" import ")[0].strip()
        else:
            name = text
        if name:
            packages.add(name.split(".")[0])
    
    if not packages:
        return ""
        
    lines = ["# PACKAGES\n"]
    for pkg in sorted(packages):
        lines.append(f"- {pkg}")
    return "\n".join(lines)


def _should_include_part(part: Part, flags: dict) -> bool:
    """Check if a part should be included based on config flags."""
    if part.type == PART_IMPORT_REL:
        return flags["include_rel"]
    if part.type == PART_IMPORT_ABS:
        return flags["include_abs"]
    if part.type == PART_FUNCTION:
        is_method = "." in part.text.split("(")[0]
        return flags["include_methods"] if is_method else flags["include_functions"]
    if part.type == PART_CLASS:
        return flags["include_classes"]
    return True  # docstrings always included


def filter_rows(rows: List[SkeletonEntry]) -> List[SkeletonEntry]:
    """Filter row content based on configuration flags."""
    flags = {
        "include_functions": get_functions_flag(),
        "include_classes": get_class_definitions_flag(),
        "include_methods": get_class_methods_flag(),
        "include_rel": get_relative_imports_flag(),
        "include_abs": get_absolute_imports_flag(),
    }
    
    filtered: List[SkeletonEntry] = []
    for row in rows:
        if row.file_type != "code":
            filtered.append(row)
            continue
        
        new_parts = [p for p in row.content if _should_include_part(p, flags)]
        filtered.append(SkeletonEntry(source=row.source, file_type=row.file_type, content=new_parts))
    
    return filtered


def _get_relative_path(source: str, root_dir: str | None) -> str:
    """Get path relative to root_dir, falling back to source unchanged."""
    if not root_dir:
        return source
    try:
        return str(Path(source).relative_to(root_dir))
    except ValueError:
        root_str = str(root_dir).rstrip("/") + "/"
        if source.startswith(root_str):
            return source[len(root_str):]
        return source


def _render_rows(rows: List[SkeletonEntry], header: str = "", root_dir: str | None = None) -> str:
    """Render rows into Markdown format with hierarchical path-based headers."""
    lines: List[str] = []
    if header:
        lines.append(header)
        lines.append("")

    emitted_dirs: set = set()

    for row in rows:
        if row.content and ': (none)' in row.content[0].text:
            continue

        # Group parts by type, nesting methods under their class
        docstrings: List[str] = []
        imports: List[str] = []
        classes_order: List[str] = []
        classes_dict: dict = {}
        methods_by_class: dict = {}
        top_level_funcs: List[str] = []

        for p in row.content:
            if p.type == PART_DOCSTRING:
                docstrings.append(p.text)
            elif p.type in (PART_IMPORT_REL, PART_IMPORT_ABS):
                imports.append(p.text)
            elif p.type == PART_CLASS:
                class_name = p.text.split(":")[0].strip()
                classes_dict[class_name] = p.text
                classes_order.append(class_name)
                methods_by_class[class_name] = []
            elif p.type == PART_FUNCTION:
                func_before_paren = p.text.split("(")[0]
                if "." in func_before_paren:
                    class_name = func_before_paren.split(".")[0]
                    if class_name in methods_by_class:
                        methods_by_class[class_name].append(p.text)
                    else:
                        top_level_funcs.append(p.text)
                else:
                    top_level_funcs.append(p.text)

        if not any([docstrings, imports, classes_order, top_level_funcs]):
            continue

        rel = _get_relative_path(row.source, root_dir)
        parts = Path(rel).parts

        # Emit a header for each directory component not yet seen
        for depth in range(1, len(parts)):
            dir_key = "/".join(parts[:depth])
            if dir_key not in emitted_dirs:
                emitted_dirs.add(dir_key)
                lines.append(f"{'#' * depth} {parts[depth - 1]}")
                lines.append("")

        # File header at the depth matching its position in the path
        file_depth = len(parts)
        lines.append(f"{'#' * file_depth} {rel}")
        lines.append("")

        if docstrings:
            lines.append(" ".join(docstrings))
            lines.append("")

        if imports:
            lines.append("**Imports**")
            for im in imports:
                lines.append(f"- `{im}`")
            lines.append("")

        if classes_order:
            lines.append("**Classes**")
            for class_name in classes_order:
                lines.append(f"- {classes_dict[class_name]}")
                for method in methods_by_class.get(class_name, []):
                    lines.append(f"  - {method}")
            lines.append("")

        if top_level_funcs:
            lines.append("**Functions**")
            for f in top_level_funcs:
                lines.append(f"- {f}")
            lines.append("")

    return "\n".join(lines)


def code_skeleton(index: List[dict], root_dir: str | None = None) -> str:
    """Generate skeleton string from index list.

    `index` is a list of dicts like {"file_path": "relative/path.py"}.
    Python files (.py) are processed with process_code().
    Documentation files (.md, .rst, .txt) are processed with process_doc().
    """
    rows: List[SkeletonEntry] = []

    for entry in index:
        file_path = get_path(entry, root_dir)
        if not file_path:
            continue
        
        fp = entry.get("file_path")
        if fp.endswith(".py"):
            rows.extend(process_code(file_path))
        elif fp.endswith((".md", ".rst", ".txt")):
            rows.extend(process_doc(file_path))
        # Other file types are silently skipped

    # Generate header from absolute imports before filtering
    header_parts = [p for row in rows for p in row.content if p.type == PART_IMPORT_ABS]
    header = import_summarize(header_parts)
    
    # Apply filtering and render
    rows = filter_rows(rows)
    return _render_rows(rows, header=header, root_dir=root_dir)


def skeleton_pipeline(repo_path) -> int:
    """Index repo directory and generate skeleton.md into .analysis/.

    Returns:
        0 on success, 1 on failure
    """
    try:
        indexed = get_index(str(repo_path))
        print(f"✓ Indexed {len(indexed)} files")
        if not indexed:
            print("⚠ No files to process")
            return 1
    except Exception as e:
        logger.error(f"Indexing failed: {e}")
        return 1

    try:
        skeleton_text = code_skeleton(indexed, root_dir=str(repo_path))

        analysis_dir = repo_path / ".analysis"
        analysis_dir.mkdir(exist_ok=True)
        skeleton_file = analysis_dir / "skeleton.md"
        skeleton_file.write_text(skeleton_text, encoding="utf-8")
        print(f"\n✓ Skeleton saved to: {skeleton_file}")

    except Exception as e:
        logger.error(f"Skeleton generation failed: {e}")
        return 1

    return 0


def main() -> int:
    """Run skeleton generation on a directory (default: current directory).

    Usage:
        python3 -m src.py_summarizer.naive_skeleton [PATH]
    """
    import sys
    repo_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    if not repo_path.is_dir():
        print(f"Error: not a directory: {repo_path}", file=sys.stderr)
        return 1
    return skeleton_pipeline(repo_path)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["code_skeleton", "skeleton_pipeline", "process_code", "process_doc", "SkeletonEntry", "Part"]
