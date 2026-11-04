"""Self-edit guardrail checks.

These tests are the point: a self-editing tool is only trustworthy
if its refusal paths are tested, not just its happy path.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mini_ai.self_edit import (
    SelfEditError, apply_edit, propose_edit, revert,
)


def make_project():
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    (root / "example.py").write_text("x = 1\n")
    (root / "mini_ai").mkdir()
    (root / "mini_ai" / "self_edit.py").write_text("# guardrails\n")
    return tmp, root


class TestSelfEdit(unittest.TestCase):
    def test_propose_does_not_write(self):
        tmp, root = make_project()
        with tmp:
            proposal = propose_edit(root, "example.py", "x = 1\n", "x = 2\n")
            self.assertIn("x = 2", proposal.diff)
            self.assertEqual((root / "example.py").read_text(), "x = 1\n")

    def test_apply_requires_approval(self):
        tmp, root = make_project()
        with tmp:
            proposal = propose_edit(root, "example.py", "x = 1\n", "x = 2\n")
            with self.assertRaises(SelfEditError):
                apply_edit(root, proposal, approved=False)
            self.assertEqual((root / "example.py").read_text(), "x = 1\n")

    def test_apply_with_approval_and_revert(self):
        tmp, root = make_project()
        with tmp:
            proposal = propose_edit(root, "example.py", "x = 1\n", "x = 2\n")
            apply_edit(root, proposal, approved=True)
            self.assertEqual((root / "example.py").read_text(), "x = 2\n")
            revert(root, "example.py")
            self.assertEqual((root / "example.py").read_text(), "x = 1\n")

    def test_apply_rolls_back_on_test_failure(self):
        tmp, root = make_project()
        with tmp:
            proposal = propose_edit(root, "example.py", "x = 1\n", "x = 2\n")
            with self.assertRaises(SelfEditError):
                apply_edit(root, proposal, approved=True,
                           test_command=[sys.executable, "-c", "import sys; sys.exit(1)"])
            self.assertEqual((root / "example.py").read_text(), "x = 1\n")

    def test_protected_file_cannot_be_edited(self):
        tmp, root = make_project()
        with tmp:
            with self.assertRaises(SelfEditError):
                propose_edit(root, "mini_ai/self_edit.py", "# guardrails\n", "# changed\n")

    def test_all_guardrail_files_are_protected(self):
        # SAFETY.md, .gitignore, and the guardrail tests themselves
        # must also be uneditable by the model, not just self_edit.py.
        tmp, root = make_project()
        with tmp:
            (root / "SAFETY.md").write_text("rules\n")
            (root / ".gitignore").write_text("checkpoints/\n")
            (root / "tests").mkdir(exist_ok=True)
            (root / "tests" / "test_self_edit.py").write_text("# tests\n")
            for path, old in [
                ("SAFETY.md", "rules\n"),
                (".gitignore", "checkpoints/\n"),
                ("tests/test_self_edit.py", "# tests\n"),
                ("./mini_ai/self_edit.py", "# guardrails\n"),
            ]:
                with self.assertRaises(SelfEditError, msg=path):
                    propose_edit(root, path, old, "changed\n")

    def test_backup_file_cannot_be_edited_directly(self):
        tmp, root = make_project()
        with tmp:
            backup = root / "example.py.self_edit_backup"
            backup.write_text("x = 1\n")
            with self.assertRaises(SelfEditError):
                propose_edit(root, "example.py.self_edit_backup", "x = 1\n", "x = 2\n")

    def test_path_escape_is_refused(self):
        tmp, root = make_project()
        with tmp:
            with self.assertRaises(SelfEditError):
                propose_edit(root, "../outside.py", "a", "b")

    def test_ambiguous_match_is_refused(self):
        tmp, root = make_project()
        with tmp:
            (root / "example.py").write_text("x = 1\nx = 1\n")
            with self.assertRaises(SelfEditError):
                propose_edit(root, "example.py", "x = 1\n", "x = 2\n")


if __name__ == "__main__":
    unittest.main()
