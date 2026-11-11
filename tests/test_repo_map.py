"""Tests for mini_ai.repo_map — the Aider-inspired repo map.

Builds a small synthetic tree in a temp dir (Python files with
known classes/functions, a test file, a doc, a data file, a protected
file, a __pycache__ dir) and checks the map lists the expected
files/symbols, skips the noise, flags protected files non-editable
without offering their symbols, modifies nothing, summarises
over-cap files, and round-trips through JSON. No Aider code, no
network, no real repo files are touched.
"""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mini_ai.repo_map import (
    MAX_LINES_FULL,
    MAX_SYMBOLS_SUMMARISED,
    SKIP_DIRS,
    build_repo_map,
    classify_kind,
    extract_symbols,
    map_from_json,
    map_to_json,
)
from mini_ai.self_edit import PROTECTED

MODULE_SRC = '''"""A tiny module."""

import os

CONSTANT = 42
other = "x"


class Widget:
    """A widget."""

    def start(self):
        pass

    def stop(self):
        pass


class Plain:
    pass


def helper(a, b):
    return a + b


async def fetch():
    return None
'''

TEST_SRC = '''import unittest


class TestWidget(unittest.TestCase):
    def test_start(self):
        pass


def check():
    pass
'''


def _write(root, rel, text):
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def _build_tree(root):
    _write(root, "mini_ai/widget.py", MODULE_SRC)
    _write(root, "tests/test_widget.py", TEST_SRC)
    _write(root, "README.md", "# Title\n\nSome prose.\n")
    _write(root, "data/values.csv", "a,b\n1,2\n")
    _write(root, "config.json", '{"key": 1}\n')
    # A protected file: present in the tree, must be listed but
    # never offered as editable and never with symbols.
    _write(root, "SAFETY.md", "# Safety\n\nclass Secret:\n    pass\n\ndef hidden():\n    pass\n")
    # Noise that must be skipped.
    _write(root, "__pycache__/widget.pyc", "not real bytecode")
    _write(root, ".venv/lib/dummy.py", "def dummy():\n    pass\n")
    _write(root, ".git/config", "[core]\n")
    _write(root, "target/debug/build.rs", "fn main() {}\n")
    return root


def _snapshot(root):
    """Map rel path -> (bytes, mtime_ns) for every file under root."""
    snap = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            with open(full, "rb") as f:
                snap[rel] = (f.read(), os.stat(full).st_mtime_ns)
    return snap


class TestClassifyAndExtract(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(classify_kind("mini_ai/widget.py"), "python")
        self.assertEqual(classify_kind("tests/test_widget.py"), "test")
        self.assertEqual(classify_kind("mini_ai/test_thing.py"), "test")
        self.assertEqual(classify_kind("README.md"), "doc")
        self.assertEqual(classify_kind("notes.txt"), "doc")
        self.assertEqual(classify_kind("data/values.csv"), "data")
        self.assertEqual(classify_kind("config.json"), "config")
        self.assertEqual(classify_kind("pyproject.toml"), "config")
        self.assertEqual(classify_kind("image.png"), "other")

    def test_extract_symbols(self):
        symbols = extract_symbols(MODULE_SRC)
        self.assertEqual([c["name"] for c in symbols["classes"]],
                         ["Widget", "Plain"])
        widget = symbols["classes"][0]
        self.assertEqual(widget["methods"], ["start", "stop"])
        self.assertEqual(symbols["classes"][1]["methods"], [])
        self.assertEqual(symbols["functions"], ["helper", "fetch"])
        self.assertIn("CONSTANT", symbols["names"])
        self.assertIn("other", symbols["names"])
        self.assertIn("os", symbols["names"])  # import alias listed

    def test_extract_parse_error(self):
        symbols = extract_symbols("def broken(:\n")
        self.assertEqual(symbols["classes"], [])
        self.assertEqual(symbols["functions"], [])
        self.assertIn("parse_error", symbols)


class TestBuildRepoMap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        _build_tree(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_lists_expected_files_and_skips_noise(self):
        result = build_repo_map(self.tmp.name)
        paths = [f["path"] for f in result["files"]]
        self.assertIn("mini_ai/widget.py", paths)
        self.assertIn("tests/test_widget.py", paths)
        self.assertIn("README.md", paths)
        self.assertIn("data/values.csv", paths)
        self.assertIn("config.json", paths)
        self.assertIn("SAFETY.md", paths)
        for noisy in ("__pycache__/widget.pyc", ".venv/lib/dummy.py",
                      ".git/config", "target/debug/build.rs"):
            self.assertNotIn(noisy, paths)
        self.assertEqual(result["schema_version"], 1)
        self.assertFalse(result["verified"])
        self.assertTrue(result["needs_human_decision"])
        self.assertFalse(result["truncated"])
        self.assertEqual(result["skipped_dirs"], sorted(SKIP_DIRS))

    def test_python_symbols(self):
        result = build_repo_map(self.tmp.name)
        by_path = {f["path"]: f for f in result["files"]}
        widget = by_path["mini_ai/widget.py"]
        self.assertEqual(widget["kind"], "python")
        self.assertEqual(widget["lines"], MODULE_SRC.count("\n"))
        self.assertTrue(widget["editable"])
        self.assertIsNone(widget["editable_reason"])
        self.assertEqual(
            [c["name"] for c in widget["symbols"]["classes"]],
            ["Widget", "Plain"])
        self.assertEqual(widget["symbols"]["functions"],
                         ["helper", "fetch"])
        test_file = by_path["tests/test_widget.py"]
        self.assertEqual(test_file["kind"], "test")
        self.assertEqual(
            [c["name"] for c in test_file["symbols"]["classes"]],
            ["TestWidget"])
        self.assertEqual(test_file["symbols"]["functions"], ["check"])

    def test_non_python_files_have_no_symbols(self):
        result = build_repo_map(self.tmp.name)
        by_path = {f["path"]: f for f in result["files"]}
        for rel in ("README.md", "data/values.csv", "config.json"):
            self.assertEqual(by_path[rel]["symbols"],
                             {"classes": [], "functions": [], "names": []})
        self.assertEqual(by_path["README.md"]["kind"], "doc")
        self.assertEqual(by_path["data/values.csv"]["kind"], "data")
        self.assertEqual(by_path["config.json"]["kind"], "config")

    def test_counts(self):
        result = build_repo_map(self.tmp.name)
        counts = result["counts"]
        self.assertEqual(counts["total"], 6)
        self.assertEqual(counts["python"], 1)
        self.assertEqual(counts["test"], 1)
        self.assertEqual(counts["doc"], 2)  # README.md + SAFETY.md
        self.assertEqual(counts["data"], 1)
        self.assertEqual(counts["config"], 1)
        self.assertEqual(counts["protected"], 1)

    def test_protected_files_flagged_and_symbols_withheld(self):
        # Every protected file on the self-edit list that is present
        # in the tree must be flagged non-editable with a protected
        # reason, and its symbols must not be offered.
        result = build_repo_map(self.tmp.name)
        by_path = {f["path"]: f for f in result["files"]}
        self.assertIn("SAFETY.md", PROTECTED)
        safety = by_path["SAFETY.md"]
        self.assertFalse(safety["editable"])
        self.assertEqual(safety["editable_reason"], "protected")
        self.assertEqual(safety["symbols"],
                         {"classes": [], "functions": [], "names": []})
        # The class/function defined in the protected file's text
        # must not appear anywhere in the map as editable content.
        blob = json.dumps(result)
        self.assertNotIn("Secret", blob)
        self.assertNotIn("hidden", blob)

    def test_protected_list_is_the_self_edit_list(self):
        # The module must read the exact list from self_edit, not a
        # re-typed copy: check a few entries beyond SAFETY.md.
        for rel in ("mini_ai/self_edit.py", "APPROVAL_POLICY.md",
                    ".gitignore", "tests/test_self_edit.py",
                    "self_edit_audit.jsonl"):
            self.assertIn(rel, PROTECTED)
        # And that a protected Python file is also symbol-withheld.
        _write(self.tmp.name, "mini_ai/self_edit.py",
               "class Guard:\n    pass\n")
        result = build_repo_map(self.tmp.name)
        by_path = {f["path"]: f for f in result["files"]}
        entry = by_path["mini_ai/self_edit.py"]
        self.assertFalse(entry["editable"])
        self.assertEqual(entry["editable_reason"], "protected")
        self.assertEqual(entry["symbols"]["classes"], [])

    def test_read_only(self):
        before = _snapshot(self.tmp.name)
        # Give mtimes a chance to differ if anything were rewritten.
        time.sleep(0.02)
        build_repo_map(self.tmp.name)
        build_repo_map(self.tmp.name)
        after = _snapshot(self.tmp.name)
        self.assertEqual(before, after)

    def test_size_cap_summarises_large_file(self):
        big = "".join(f"def func_{i}():\n    pass\n\n" for i in range(300))
        # 300 functions, well over MAX_LINES_FULL lines.
        self.assertGreater(big.count("\n"), MAX_LINES_FULL)
        _write(self.tmp.name, "mini_ai/big.py", big)
        result = build_repo_map(self.tmp.name)
        by_path = {f["path"]: f for f in result["files"]}
        entry = by_path["mini_ai/big.py"]
        self.assertTrue(entry["summarised"])
        total = (len(entry["symbols"]["classes"])
                 + len(entry["symbols"]["functions"])
                 + len(entry["symbols"]["names"]))
        self.assertLessEqual(total, MAX_SYMBOLS_SUMMARISED)
        self.assertEqual(entry["lines"], big.count("\n"))
        self.assertEqual(result["counts"]["summarised"], 1)

    def test_json_round_trip(self):
        result = build_repo_map(self.tmp.name)
        text = map_to_json(result)
        restored = map_from_json(text)
        self.assertEqual(restored, result)
        # And the plain json module agrees (no exotic types).
        self.assertEqual(json.loads(text), result)

    def test_empty_tree(self):
        with tempfile.TemporaryDirectory() as empty:
            result = build_repo_map(empty)
            self.assertEqual(result["files"], [])
            self.assertEqual(result["counts"]["total"], 0)
            self.assertFalse(result["verified"])
            self.assertTrue(result["needs_human_decision"])


if __name__ == "__main__":
    unittest.main()
