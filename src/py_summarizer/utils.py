"""Utility helpers for the project (logging, config, indexing)."""

import ast
import asyncio
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Optional

import yaml


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Return a configured logger for the application.

    The logger prints to stderr with a simple format. Multiple calls
    return the same logger instance (handlers are added only once).
    """
    logger_name = name or "ghsummarizer"
    logger = logging.getLogger(logger_name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
        handler.setFormatter(fmt)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


logger = get_logger(__name__)


def load_config(config_path: Optional[Path] = None) -> dict:
    """Load configuration from YAML file.

    Args:
        config_path: Path to config.yml. If None, looks for config.yml in project root.

    Returns:
        Dictionary containing configuration settings.
    """
    if config_path is None:
        current_dir = Path(__file__).parent.parent
        config_path = current_dir / "config.yml"

    if not config_path.exists():
        logger.warning(f"Config file not found at {config_path}, using defaults")
        return {
            "skipped_dirs": ["example", "examples", "test", "tests", "contrib"],
            "skipped_patterns": [],
            "class_methods": False,
            "max_prompt_tokens": 6000,
        }

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        return config or {}
    except Exception as e:
        logger.error(f"Failed to load config from {config_path}: {e}")
        return {
            "skipped_dirs": ["example", "examples", "test", "tests", "contrib"],
            "skipped_patterns": [],
            "class_methods": False,
            "max_prompt_tokens": 6000,
        }


def get_import_config(config_path: Optional[Path] = None) -> dict:
    """Get import config section (relative_imports, absolute_imports)."""
    config = load_config(config_path)
    return config.get("import", {"relative_imports": True, "absolute_imports": True})


def get_relative_imports_flag(config_path: Optional[Path] = None) -> bool:
    """Return True if relative imports should be included."""
    return get_import_config(config_path).get("relative_imports", True)


def get_absolute_imports_flag(config_path: Optional[Path] = None) -> bool:
    """Return True if absolute imports should be included."""
    return get_import_config(config_path).get("absolute_imports", True)


def get_skipped_dirs(config_path: Optional[Path] = None) -> list[str]:
    """Get list of directory names to skip during skeleton generation."""
    return load_config(config_path).get("skipped_dirs", [])


def get_class_definitions_flag(config_path: Optional[Path] = None) -> bool:
    """Return True if class definitions should be included in skeleton output."""
    config = load_config(config_path)
    return config.get("classes", {}).get("definitions", True)


def get_class_methods_flag(config_path: Optional[Path] = None) -> bool:
    """Return True if class methods should be included in skeleton output."""
    config = load_config(config_path)
    classes_config = config.get("classes", {})
    if not classes_config.get("definitions", True):
        return False
    return classes_config.get("methods", False)


def get_functions_flag(config_path: Optional[Path] = None) -> bool:
    """Return True if functions should be included in skeleton output."""
    return load_config(config_path).get("functions", True)


def get_text_extensions(config_path: Optional[Path] = None) -> list[str]:
    """Get list of file extensions to include during indexing."""
    return load_config(config_path).get("text_extensions", [".py", ".txt", ".md"])


def clean_markdown_text(text: str) -> str:
    """Remove links, HTML tags, code blocks, and heading symbols from markdown text."""
    text = re.sub(r'(```[\s\S]*?```|~~~[\s\S]*?~~~)', '', text)
    text = re.sub(r'`[^`]+`', '', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)
    text = '\n'.join(line for line in text.splitlines() if line.strip())
    return text.strip()


def short_doc(node: ast.AST, max_len: int = 120) -> str:
    """Return first docstring line truncated to `max_len` characters."""
    doc = ast.get_docstring(node) or ""
    if not doc:
        return ""
    first_line = doc.strip().splitlines()[0]
    return (first_line[: max_len - 3] + "...") if len(first_line) > max_len else first_line


def resolve_file_path(fp: str, root_dir: str | None) -> Path | None:
    """Resolve file path by trying raw path, root_dir-relative, then cwd-relative."""
    path = Path(fp)
    if path.exists():
        return path
    if not path.is_absolute() and root_dir:
        path = Path(root_dir) / fp
        if path.exists():
            return path
    path = Path.cwd() / fp
    return path if path.exists() else None


def should_skip_by_dir(path: Path) -> bool:
    """Return True when any path segment matches configured skipped dirs."""
    skipped_dirs = get_skipped_dirs()
    return any(any(skip_dir in part.lower() for skip_dir in skipped_dirs) for part in path.parts)


def get_path(entry: dict, root_dir: str | None = None) -> Path | None:
    """Resolve and validate file path from index entry with skip rules and logging."""
    fp = entry.get("file_path")
    if not fp:
        return None
    path = Path(fp)
    if should_skip_by_dir(path):
        return None
    resolved_path = resolve_file_path(fp, root_dir)
    if not resolved_path:
        get_logger(__name__).warning(f"Skipped (missing): {fp}")
        return None
    return resolved_path


def get_index(root_dir_path: str) -> list[dict[str, str]]:
    """Return a flat list of dicts with key `file_path` for files under root.

    `file_path` values are POSIX-style relative paths (strings) relative
    to `root_dir_path`.

    Behavior:
    - Walks the directory tree recursively.
    - Skips any file or directory whose name starts with a dot (`.`).
    - Skips any files under a `__pycache__` directory.
    - Skips directories configured in skipped_dirs (from config.yml).
    - Filters files by extension: if a file has an extension, it must be
      one of the extensions listed in text_extensions (from config.yml).
      Files without an extension are included (treated as text).
    """
    root = Path(root_dir_path).resolve()
    results: list[dict[str, str]] = []
    if not root.exists() or not root.is_dir():
        return results

    excluded_dirs: set[str] = {d.lower() for d in get_skipped_dirs()}
    text_extensions: set[str] = {ext.lower() for ext in get_text_extensions()}

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith('.') and d.lower() not in excluded_dirs]
        for fname in filenames:
            if fname.startswith('.'):
                continue
            full = Path(dirpath) / fname
            if "__pycache__" in full.parts:
                continue
            ext = full.suffix.lower()
            if ext and ext not in text_extensions:
                continue
            results.append({"file_path": full.relative_to(root).as_posix()})

    return results


async def clone_repo(repo_url: str, timeout: int = 120) -> Path:
    """Clone `repo_url` into a subdirectory under `os.environ['DATA_DIR']`.

    The directory is created with `tempfile.mkdtemp(dir=DATA_DIR, prefix=...)`.
    If `DATA_DIR` is not set in the environment a RuntimeError is raised.
    On failure the created directory is removed and a RuntimeError is raised.
    """
    try:
        base_dir = os.environ["DATA_DIR"]
    except KeyError:
        raise RuntimeError("Environment variable DATA_DIR must be set and writable")

    base_path = Path(base_dir)
    base_path.mkdir(parents=True, exist_ok=True)

    slug = repo_url.rstrip("/")
    if "github.com/" in slug:
        slug = slug.split("github.com/")[-1]
    if slug.endswith(".git"):
        slug = slug[: -len(".git")]

    target_path = base_path.joinpath(*slug.split("/"))

    if target_path.exists():
        logger.info("Repository already present at %s — skipping clone", target_path)
        return target_path

    target_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["git", "clone", "--depth=1", "--single-branch", "--no-tags", repo_url, str(target_path)]

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        shutil.rmtree(target_path, ignore_errors=True)
        raise RuntimeError("Clone timed out")

    if proc.returncode != 0:
        shutil.rmtree(target_path, ignore_errors=True)
        err = stderr.decode(errors="ignore").strip()
        logger.error("Clone failed for %s: %s", repo_url, err)
        raise RuntimeError(f"Clone failed: {err}")

    logger.info("Successfully cloned %s -> %s", repo_url, target_path)
    return Path(target_path)


__all__ = [
    "get_logger",
    "clone_repo",
    "load_config",
    "get_skipped_dirs",
    "get_class_methods_flag",
    "get_text_extensions",
    "get_index",
    "short_doc",
    "resolve_file_path",
    "should_skip_by_dir",
    "get_path",
]
