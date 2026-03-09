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

from .code_graph import check_function_important, extract_classes
from .utils import (
    clean_markdown_text,
    get_absolute_imports_flag,
    get_class_definitions_flag,
    get_class_methods_flag,
    get_functions_flag,
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
    summary = ", ".join(sorted(packages))
    return f"PACKAGES: {summary}" if summary else ""


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


def _render_rows(rows: List[SkeletonEntry], header: str = "") -> str:
    """Render rows into valid YAML format with folded block scalars for docstrings."""
    lines: List[str] = []
    if header:
        lines.append(header)
        lines.append("")
    
    for row in rows:
        if row.content and ': (none)' in row.content[0].text:
            continue
        prefix = "File" if row.file_type == "code" else "Documentation"
        lines.append(f"{prefix}: {row.source}")
        
        # Group parts by type
        by_type = {
            PART_DOCSTRING: [],
            "imports": [],
            PART_FUNCTION: [],
            PART_CLASS: [],
        }
        
        for p in row.content:
            if p.type == PART_DOCSTRING:
                by_type[PART_DOCSTRING].append(p.text)
            elif p.type in (PART_IMPORT_REL, PART_IMPORT_ABS):
                by_type["imports"].append(p.text)
            elif p.type == PART_FUNCTION:
                by_type[PART_FUNCTION].append(p.text)
            elif p.type == PART_CLASS:
                by_type[PART_CLASS].append(p.text)
        
        # Render each section as YAML
        # Docstring: use folded block scalar (>) for long content, otherwise inline
        if by_type[PART_DOCSTRING]:
            docstring_text = " ".join(by_type[PART_DOCSTRING])
            if len(docstring_text) > 120:
                lines.append("Docstring: >")
                # Wrap text at ~80 chars while preserving word boundaries
                words = docstring_text.split()
                current_line = []
                for word in words:
                    test_line = " ".join(current_line + [word])
                    if len(test_line) > 80 and current_line:
                        lines.append(f"  {' '.join(current_line)}")
                        current_line = [word]
                    else:
                        current_line.append(word)
                if current_line:
                    lines.append(f"  {' '.join(current_line)}")
            else:
                lines.append(f"Docstring: {docstring_text!r}")
        
        if by_type["imports"]:
            lines.append("Imports:")
            lines.extend(f"  - {im}" for im in by_type["imports"])
        
        if by_type[PART_CLASS]:
            lines.append("Classes:")
            lines.extend(f"  - {c}" for c in by_type[PART_CLASS])
        
        if by_type[PART_FUNCTION]:
            lines.append("Functions:")
            lines.extend(f"  - {f}" for f in by_type[PART_FUNCTION])
        
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
    return _render_rows(rows, header=header)


__all__ = ["code_skeleton", "process_code", "process_doc", "SkeletonEntry", "Part"]
