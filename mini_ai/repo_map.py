"""Compact repo map for the proposer — original Python, rebuilt from
the Aider repo-map idea (see the sweep:
``start-assembly/core-spine/source-audit/ALL_CANDIDATES_BORROWING_PLAN.md``,
Module 20 — Aider-AI/aider, Apache-2.0, 20,285 lines; its repo map is
``aider/repomap.py``, 867 lines: tree-sitter tag extraction plus
ranked, token-budgeted whole-repo context).

No Aider code was read or copied and there is no Aider dependency:
only the design shape was rebuilt, as original Python, in this
module — a compact map of a repo tree (files, kinds, top-level
symbols) for the proposer to consult when drafting a diff. Where
Aider uses tree-sitter, this module uses the stdlib ``ast`` module
and never imports the files it maps. Where Aider ranks tags under a
token budget, this module caps file size and symbol counts (see
``MAX_LINES_FULL`` / ``MAX_SYMBOLS_*`` below) and summarises the
largest files instead of dumping them.

READ-ONLY BY CONSTRUCTION: this module only walks the tree
(``os.walk``), opens files for reading, and parses Python source
with ``ast.parse``. It never writes, renames, deletes, or otherwise
modifies anything, and it never approves a diff — a repo map is a
model result, never a verified plan. Every map carries
``verified=False`` and ``needs_human_decision=True``, following the
``mini_ai/eval`` pattern.

PROTECTED FILES: the protected list is read from
``mini_ai.self_edit.PROTECTED`` (never re-typed here, so it cannot
drift from the guardrails). Every protected file present in the tree
is listed — a proposer must be able to see that it exists — but
flagged ``editable=False`` with reason ``"protected"``, and its
symbols are NOT included: the map offers no protected content for
editing. Protected files are never editable through self-edit, even
with human approval through that module; a human edits them
directly, in an editor.

Stdlib only; no new dependency. No network, no downloads.
"""

import ast
import json
import os

try:  # Same package; fall back to an empty set only if imported standalone.
    from .self_edit import PROTECTED
except Exception:  # pragma: no cover - import fallback
    try:
        from mini_ai.self_edit import PROTECTED
    except Exception:  # pragma: no cover - import fallback
        PROTECTED = frozenset()

SCHEMA_VERSION = 1

# Size caps (the compactness budget). A Python file longer than
# MAX_LINES_FULL lines is summarised, not dumped: only its first
# MAX_SYMBOLS_SUMMARISED symbols are listed and it is flagged
# "summarised". Shorter files list up to MAX_SYMBOLS_FULL symbols.
# A tree larger than MAX_FILES files is truncated (flagged, with a
# count of the files omitted).
MAX_LINES_FULL = 500
MAX_SYMBOLS_FULL = 100
MAX_SYMBOLS_SUMMARISED = 20
MAX_FILES = 2000

# Directory names skipped at every depth: version control, caches,
# virtual environments, build outputs, and other non-source noise.
# Recorded on every map so a consumer can see what was excluded.
SKIP_DIRS = frozenset({
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".venv",
    "venv",
    "target",
    "node_modules",
    "checkpoints",
    ".tox",
    ".eggs",
    "dist",
    "build",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
})

# File names / suffixes skipped at every depth.
SKIP_NAMES = frozenset({".DS_Store"})
SKIP_SUFFIXES = frozenset({".pyc", ".pyo", ".so", ".pyd", ".pt", ".pth", ".ckpt"})

# File kinds, by suffix / name. ".txt" is a doc here (prose), while
# tabular / binary-ish data extensions are "data".
_CONFIG_SUFFIXES = frozenset({".json", ".yaml", ".yml", ".toml", ".ini", ".cfg"})
_DATA_SUFFIXES = frozenset({".csv", ".tsv", ".jsonl", ".npy", ".npz", ".parquet"})
_DOC_SUFFIXES = frozenset({".md", ".rst", ".txt"})


def classify_kind(rel_path):
    """Return the file kind for a repo-relative path.

    Kinds: "python" (a .py module), "test" (a .py test file),
    "doc", "data", "config", or "other".
    """
    name = os.path.basename(rel_path)
    suffix = os.path.splitext(name)[1].lower()
    if suffix == ".py":
        parts = rel_path.replace(os.sep, "/").split("/")
        if "tests" in parts or "test" in parts or name.startswith("test_") \
                or name.endswith("_test.py"):
            return "test"
        return "python"
    if suffix in _DOC_SUFFIXES:
        return "doc"
    if suffix in _DATA_SUFFIXES:
        return "data"
    if suffix in _CONFIG_SUFFIXES:
        return "config"
    return "other"


def _top_level_names(node):
    """Module-level assigned names from one AST statement node."""
    names = []
    if isinstance(node, ast.Assign):
        for target in node.targets:
            names.extend(_target_names(target))
    elif isinstance(node, ast.AnnAssign):
        names.extend(_target_names(node.target))
    elif isinstance(node, (ast.Import, ast.ImportFrom)):
        for alias in node.names:
            if alias.asname:
                names.append(alias.asname)
            elif isinstance(node, ast.Import):
                names.append(alias.name.split(".")[0])
    return names


def _target_names(target):
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        names = []
        for elt in target.elts:
            names.extend(_target_names(elt))
        return names
    return []


def extract_symbols(source):
    """Extract top-level symbols from Python source text.

    Returns {"classes": [{"name", "methods": [...]}], "functions":
    [...], "names": [...]}. Classes carry their method names (def
    statements directly in the class body, in order). Module-level
    assigned names and import aliases are listed under "names".
    A source that does not parse returns empty symbols plus a
    "parse_error" key with the error message; the file is still
    listed in the map.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return {"classes": [], "functions": [], "names": [],
                "parse_error": f"{exc.msg} (line {exc.lineno})"}
    classes = []
    functions = []
    names = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            methods = [n.name for n in node.body
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            classes.append({"name": node.name, "methods": methods})
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node.name)
        else:
            names.extend(_top_level_names(node))
    return {"classes": classes, "functions": functions, "names": names}


def _symbol_count(symbols):
    return (len(symbols.get("classes", [])) + len(symbols.get("functions", []))
            + len(symbols.get("names", [])))


def _truncate_symbols(symbols, limit):
    """Keep at most ``limit`` symbols, classes first, then functions,
    then names, preserving order within each group."""
    kept = {"classes": [], "functions": [], "names": []}
    remaining = limit
    for key in ("classes", "functions", "names"):
        kept[key] = symbols.get(key, [])[:remaining]
        remaining -= len(kept[key])
        if remaining <= 0:
            break
    if "parse_error" in symbols:
        kept["parse_error"] = symbols["parse_error"]
    return kept


def build_repo_map(root, max_lines_full=MAX_LINES_FULL,
                   max_symbols_full=MAX_SYMBOLS_FULL,
                   max_symbols_summarised=MAX_SYMBOLS_SUMMARISED,
                   max_files=MAX_FILES):
    """Build a compact, JSON-able map of the repo tree at ``root``.

    Read-only: walks the tree, reads files, parses Python with
    ``ast``. Writes nothing. Symlinks are not followed, and a
    symlinked file is skipped rather than resolved outside the tree.

    The returned dict has keys: ``schema_version``, ``root`` (the
    path as given), ``files`` (one entry per mapped file, sorted by
    path), ``counts`` (by kind, plus totals and skipped counts),
    ``skipped_dirs`` (the SKIP_DIRS list, sorted), ``truncated``
    (True when the MAX_FILES cap cut the listing), ``verified``
    (always False) and ``needs_human_decision`` (always True).

    Each file entry has: ``path`` (repo-relative, forward slashes),
    ``kind``, ``lines`` (line count; 0 for an unreadable file),
    ``editable`` (False for protected files), ``editable_reason``
    (``"protected"`` for protected files, else None), ``symbols``
    (classes/functions/names for Python and test files; empty for
    other kinds and for protected files), ``summarised`` (True when
    the file exceeded the line cap and its symbols were truncated)
    and, for unparseable Python, a ``parse_error`` note inside
    ``symbols``.
    """
    root = os.fspath(root)
    files = []
    counts = {"total": 0, "python": 0, "test": 0, "doc": 0, "data": 0,
              "config": 0, "other": 0, "protected": 0, "summarised": 0,
              "skipped": 0}
    truncated = False
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        # Skip noise dirs in place so os.walk never descends into them.
        kept_dirs = []
        for dirname in sorted(dirnames):
            if dirname in SKIP_DIRS or os.path.islink(os.path.join(dirpath, dirname)):
                counts["skipped"] += 1
            else:
                kept_dirs.append(dirname)
        dirnames[:] = kept_dirs
        for filename in sorted(filenames):
            if filename in SKIP_NAMES:
                counts["skipped"] += 1
                continue
            if os.path.splitext(filename)[1].lower() in SKIP_SUFFIXES:
                counts["skipped"] += 1
                continue
            full = os.path.join(dirpath, filename)
            if os.path.islink(full):
                counts["skipped"] += 1
                continue
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if len(files) >= max_files:
                truncated = True
                counts["skipped"] += 1
                continue
            kind = classify_kind(rel)
            is_protected = rel in PROTECTED
            try:
                with open(full, "r", encoding="utf-8", errors="strict") as f:
                    text = f.read()
                lines = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
            except (OSError, UnicodeDecodeError):
                # Unreadable / non-UTF-8 file: list it, offer no content.
                lines = 0
                text = None
            if is_protected:
                symbols = {"classes": [], "functions": [], "names": []}
                summarised = False
            elif kind in ("python", "test") and text is not None:
                symbols = extract_symbols(text)
                if lines > max_lines_full:
                    symbols = _truncate_symbols(symbols, max_symbols_summarised)
                    summarised = True
                elif _symbol_count(symbols) > max_symbols_full:
                    symbols = _truncate_symbols(symbols, max_symbols_full)
                    summarised = True
                else:
                    summarised = False
            else:
                symbols = {"classes": [], "functions": [], "names": []}
                summarised = False
            files.append({
                "path": rel,
                "kind": kind,
                "lines": lines,
                "editable": not is_protected,
                "editable_reason": "protected" if is_protected else None,
                "symbols": symbols,
                "summarised": summarised,
            })
            counts["total"] += 1
            counts[kind] += 1
            if is_protected:
                counts["protected"] += 1
            if summarised:
                counts["summarised"] += 1
    files.sort(key=lambda entry: entry["path"])
    return {
        "schema_version": SCHEMA_VERSION,
        "root": root,
        "files": files,
        "counts": counts,
        "skipped_dirs": sorted(SKIP_DIRS),
        "truncated": truncated,
        "verified": False,
        "needs_human_decision": True,
    }


def map_to_json(repo_map):
    """Serialise a repo map to a JSON string (sorted keys)."""
    return json.dumps(repo_map, sort_keys=True)


def map_from_json(text):
    """Deserialise a repo map from a JSON string."""
    return json.loads(text)


if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    print(map_to_json(build_repo_map(target)))
