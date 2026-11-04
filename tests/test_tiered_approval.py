"""Tiered self-approval checks.

The critical property: the tier is recomputed from the diff, not
claimed by the caller, and guardrail / high edits cannot be
self-approved even if a caller tries.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mini_ai.self_edit import (
    SelfEditError, classify_edit, propose_edit, self_approve,
)


def make_project():
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    (root / "example.py").write_text("x = 1\n")
    (root / "data").mkdir()
    (root / "data" / "corpus.txt").write_text("hello world\n")
    (root / "mini_ai").mkdir()
    (root / "mini_ai" / "self_edit.py").write_text("# guardrails\n")
    (root / "APPROVAL_POLICY.md").write_text("# policy\n")
    return tmp, root


class TestTiers(unittest.TestCase):
    def test_low_classification(self):
        tmp, root = make_project()
        with tmp:
            p = propose_edit(root, "example.py", "x = 1\n", "x = 2\n")
            tier, _ = classify_edit(root, p)
            self.assertEqual(tier, "low")

    def test_medium_classification_by_size(self):
        tmp, root = make_project()
        with tmp:
            old = "x = 1\n"
            new = "".join(f"y{i} = {i}\n" for i in range(30))
            # propose_edit needs old to match once; use a file with many lines
            (root / "example.py").write_text(old + "z = 9\n")
            p = propose_edit(root, "example.py", old, new)
            tier, _ = classify_edit(root, p)
            self.assertEqual(tier, "medium")

    def test_data_file_is_at_least_medium(self):
        tmp, root = make_project()
        with tmp:
            p = propose_edit(root, "data/corpus.txt", "hello world\n", "hello garden\n")
            tier, _ = classify_edit(root, p)
            self.assertEqual(tier, "medium")

    def test_dangerous_pattern_is_high(self):
        tmp, root = make_project()
        with tmp:
            p = propose_edit(root, "example.py", "x = 1\n", "import subprocess\nx = 1\n")
            tier, _ = classify_edit(root, p)
            self.assertEqual(tier, "high")

    def test_non_stdlib_import_is_high(self):
        tmp, root = make_project()
        with tmp:
            p = propose_edit(root, "example.py", "x = 1\n", "import requests\nx = 1\n")
            tier, _ = classify_edit(root, p)
            self.assertEqual(tier, "high")

    def test_protected_is_never_and_cannot_self_approve(self):
        tmp, root = make_project()
        with tmp:
            # propose_edit itself must refuse protected files, before classification
            with self.assertRaises(SelfEditError):
                propose_edit(root, "mini_ai/self_edit.py", "# guardrails\n", "# changed\n")
            with self.assertRaises(SelfEditError):
                propose_edit(root, "APPROVAL_POLICY.md", "# policy\n", "# changed\n")

    def test_self_approve_low_succeeds_and_logs(self):
        tmp, root = make_project()
        with tmp:
            p = propose_edit(root, "example.py", "x = 1\n", "x = 2\n")
            self_approve(root, p, test_command=[sys.executable, "-m", "py_compile", "example.py"])
            self.assertEqual((root / "example.py").read_text(), "x = 2\n")
            audit = (root / "self_edit_audit.jsonl").read_text()
            entry = json.loads(audit.strip().splitlines()[-1])
            self.assertEqual(entry["tier"], "low")
            self.assertEqual(entry["approver"], "self-low")
            self.assertFalse(entry["pending_human_review"])

    def test_self_approve_medium_succeeds_and_flags_review(self):
        tmp, root = make_project()
        with tmp:
            (root / "example.py").write_text("x = 1\nz = 9\n")
            p = propose_edit(root, "example.py", "x = 1\n",
                             "".join(f"y{i} = {i}\n" for i in range(30)))
            self_approve(root, p, test_command=[sys.executable, "-m", "py_compile", "example.py"])
            audit = (root / "self_edit_audit.jsonl").read_text()
            entry = json.loads(audit.strip().splitlines()[-1])
            self.assertEqual(entry["tier"], "medium")
            self.assertTrue(entry["pending_human_review"])

    def test_self_approve_high_raises_and_does_not_write(self):
        tmp, root = make_project()
        with tmp:
            p = propose_edit(root, "example.py", "x = 1\n", "import subprocess\nx = 1\n")
            with self.assertRaises(SelfEditError):
                self_approve(root, p, test_command=[sys.executable, "-m", "py_compile", "example.py"])
            self.assertNotIn("subprocess", (root / "example.py").read_text())

    def test_audit_log_cannot_be_edited_via_propose(self):
        tmp, root = make_project()
        with tmp:
            (root / "self_edit_audit.jsonl").write_text("{}\n")
            with self.assertRaises(SelfEditError):
                propose_edit(root, "self_edit_audit.jsonl", "{}\n", "{}\n{}\n")


if __name__ == "__main__":
    unittest.main()
