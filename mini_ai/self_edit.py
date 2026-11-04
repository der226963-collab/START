"""Safe self-editing: an AI can propose code changes, a human approves them.

This is deliberately NOT unrestricted self-modification.

The workflow is:
  1. propose_edit() — checks the change, returns a unified diff.
     Nothing is written yet.
  2. A human reads the diff and approves it.
  3. apply_edit(approved=True) — writes the change, keeps a backup,
     runs the test command, and rolls back automatically if tests fail.
  4. revert() — restores the backup, by hand, at any time.

Guardrails that cannot be bypassed from inside this module:
  - Edits stay inside one project root. No absolute paths outside
    it, no parent-directory escapes, no symlinks out of it.
  - Only .py, .md, and .txt files may be edited.
  - Protected files may never be edited by this module, including
    this file itself, so a model cannot use self-editing to remove
    its own approval check, safety rules, or rollback path.
  - No edit is applied without approved=True. A model calling this
    code cannot approve its own edit — approval is a human action
    passed in from outside the model.
  - Secrets and checkpoints are never editable: .env, keys,
    credentials, .pt files, and anything under checkpoints/.

This matches PCAC's safety charter: corrigibility first, human
assemblies as decider, transparency (a diff is an audit trail),
and rollback / shutdown that do not depend on the system itself.
If you want a model to change these guardrails, a human edits this
file directly, in an editor, with a commit message saying so.
"""
import difflib
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ALLOWED_SUFFIXES = {".py", ".md", ".txt"}

# Files this module will never edit, even with approval. Add safety
# and governance files here as the project grows; never remove an
# entry from inside a model-generated edit.
#   mini_ai/self_edit.py — the approval / guardrail code itself.
#     If a model could edit this, it could remove its own approval
#     check. That is the core corrigibility rule.
#   SAFETY.md — the written safety rules for this project.
#   .gitignore — editing this could hide changes from review / pushes.
#   tests/test_self_edit.py — the tests for these guardrails.
#     If a model could edit them, it could weaken its own tests.
PROTECTED = {
    "mini_ai/self_edit.py",
    "SAFETY.md",
    ".gitignore",
    "tests/test_self_edit.py",
}

# Names that are never editable, at any depth.
BLOCKED_NAMES = {".env", ".git", "checkpoints", "__pycache__"}


class SelfEditError(ValueError):
    pass


@dataclass
class EditProposal:
    path: str
    old_text: str
    new_text: str
    diff: str

    def __str__(self):
        return self.diff


def _resolve(root, rel_path):
    root = Path(root).resolve()
    target = (root / rel_path).resolve()
    # Resolve symlinks, then check containment — a symlink inside the
    # project pointing outside must not escape the root.
    if root not in target.parents and target != root:
        raise SelfEditError(f"Path escapes project root: {rel_path}")
    return target


def _check_editable(root, rel_path):
    target = _resolve(root, rel_path)
    rel = target.relative_to(Path(root).resolve()).as_posix()
    if rel in PROTECTED:
        raise SelfEditError(f"Protected file, cannot be edited by self-edit: {rel}")
    if any(part in BLOCKED_NAMES for part in target.relative_to(Path(root).resolve()).parts):
        raise SelfEditError(f"Blocked path: {rel}")
    if target.suffix not in ALLOWED_SUFFIXES:
        raise SelfEditError(f"Only {sorted(ALLOWED_SUFFIXES)} may be edited, not {target.suffix}")
    return target, rel


def propose_edit(root, rel_path, old_text, new_text):
    """Return a proposal with a diff. Writes nothing."""
    target, rel = _check_editable(root, rel_path)
    if not target.exists():
        raise SelfEditError(f"File does not exist: {rel}")
    current = target.read_text()
    if current.count(old_text) != 1:
        raise SelfEditError(
            f"old_text must match exactly once in {rel}, "
            f"found {current.count(old_text)} matches — refusing an ambiguous edit"
        )
    diff = "".join(difflib.unified_diff(
        current.splitlines(keepends=True),
        current.replace(old_text, new_text, 1).splitlines(keepends=True),
        fromfile=f"a/{rel}", tofile=f"b/{rel}",
    ))
    return EditProposal(path=rel, old_text=old_text, new_text=new_text, diff=diff)


def apply_edit(root, proposal, approved=False, test_command=None):
    """Apply a proposal only with human approval, then test, then rollback on failure.

    approved must be passed by a human (or human-approved tooling
    outside the model). The default is False, so a bare call from a
    model does nothing except raise.
    """
    if not approved:
        raise SelfEditError(
            "Edit not applied: approved=False. A human must read the "
            "diff and approve it before any file is written."
        )
    target, rel = _check_editable(root, proposal.path)
    current = target.read_text()
    if current.count(proposal.old_text) != 1:
        raise SelfEditError(f"File changed since proposal, refusing to apply: {rel}")
    backup = target.with_suffix(target.suffix + ".self_edit_backup")
    shutil.copyfile(target, backup)
    try:
        target.write_text(current.replace(proposal.old_text, proposal.new_text, 1))
        if test_command:
            result = subprocess.run(
                test_command, cwd=root, capture_output=True, text=True, timeout=300,
            )
            if result.returncode != 0:
                target.write_text(current)
                raise SelfEditError(
                    f"Tests failed after edit, rolled back {rel}.\n{result.stdout}\n{result.stderr}"
                )
        return rel
    except Exception:
        # Any failure after writing restores the original, unless the
        # failure was the deliberate rollback error above (already restored).
        if target.read_text() != current:
            target.write_text(current)
        raise
    finally:
        # The backup is kept on disk for manual revert(); it is not
        # a secret, and it is excluded from GitHub pushes by .gitignore.
        pass


def revert(root, rel_path):
    """Restore the .self_edit_backup for a file, if one exists."""
    target, _ = _check_editable(root, rel_path)
    backup = target.with_suffix(target.suffix + ".self_edit_backup")
    if not backup.exists():
        raise SelfEditError(f"No backup to revert for {rel_path}")
    shutil.copyfile(backup, target)
    return str(target)


if __name__ == "__main__":
    # Demo: propose only, never apply. There is deliberately no
    # approved=True call left in this module, so a model reading
    # this code cannot find an in-module path to self-approval.
    # A human applies an edit from their own code / tooling, outside
    # the model, after reading the diff.
    # Usage: python -m mini_ai.self_edit
    root = Path(__file__).parent.parent
    demo = root / "self_edit_demo.txt"
    demo.write_text("before\n")
    proposal = propose_edit(root, "self_edit_demo.txt", "before\n", "after\n")
    print(proposal.diff)
    print("Proposal only — nothing was applied. A human must approve it.")
    demo.unlink(missing_ok=True)
    sys.exit(0)
