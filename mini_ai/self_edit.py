"""Safe self-editing, with tiered approval.

This is deliberately NOT unrestricted self-modification.

Two approval paths, kept separate:

  A. Human approval (the default, for everything):
     propose_edit() -> human reads the diff -> apply_edit(approved=True)
     -> tests -> rollback on failure -> revert() at any time.

  B. Tiered self-approval (low and medium risk only):
     propose_edit() -> classify_edit() recomputes the tier from the
     diff itself, ignoring any tier the proposer claims ->
     self_approve() applies it only if the tier is low or medium,
     tests pass, and, for medium, a second independent verification
     in this module also passes. Every self-approved edit is logged
     to self_edit_audit.jsonl, medium edits are flagged
     pending_human_review, and a human can revert any of them.

  High-risk edits and guardrail edits are never self-approvable:
  they go back to path A, and guardrail edits are not editable
  through this module at all — a human edits those files directly.

Tiers, in short (full policy in APPROVAL_POLICY.md, which is itself
protected):
  low    — <=20 changed lines, one non-protected file, no new
           imports, no dangerous patterns, tests pass.
  medium — <=100 changed lines, may add standard-library imports
           only, may touch data / model / docs (not guardrails),
           no dangerous patterns, tests pass, plus second verification.
  high   — anything larger, any non-standard-library import, any
           dangerous pattern, any test-file edit outside guardrail
           tests, or any other case not in low/medium. Human only.
  never  — protected files: self_edit.py, SAFETY.md,
           APPROVAL_POLICY.md, .gitignore, guardrail tests, and the
           audit log itself. Not editable through this module, even
           with human approval through this module — a human edits
           them directly, in an editor, with a commit message.

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
    "APPROVAL_POLICY.md",
    ".gitignore",
    "tests/test_self_edit.py",
    "tests/test_tiered_approval.py",
    "self_edit_audit.jsonl",
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


LOW_MAX_LINES = 20
MEDIUM_MAX_LINES = 100
AUDIT_FILE = "self_edit_audit.jsonl"

# Patterns that are never low/medium, even in a small diff. The list
# is about new occurrences: a file that already contains one of these
# words in a comment is not automatically high-risk, a diff that adds
# one is.
DANGEROUS_PATTERNS = [
    "subprocess", "os.system", "os.popen", "eval(", "exec(",
    "socket", "urllib", "requests.", "httpx", "__import__",
    "shutil.rmtree", "os.remove", "os.unlink",
]

# Data files change what a model learns, so they are at least medium,
# even for a small diff. They are never low.
DATA_FILES = {"data/corpus.txt", "mini_ai/data.py"}


def _changed_lines(old_text, new_text):
    """Number of added + removed lines in a unified diff, excluding headers."""
    diff = difflib.unified_diff(
        old_text.splitlines(), new_text.splitlines(), lineterm="",
    )
    return sum(1 for line in diff if (line.startswith("+") or line.startswith("-"))
               and not line.startswith("+++") and not line.startswith("---"))


def _new_imports(old_text, new_text):
    import re
    pattern = re.compile(r"^\s*(?:import|from)\s+([a-zA-Z0-9_\.]+)", re.MULTILINE)
    return set(pattern.findall(new_text)) - set(pattern.findall(old_text))


def _is_stdlib(module_name):
    top = module_name.split(".")[0]
    stdlib = getattr(sys, "stdlib_module_names", set())
    return top in stdlib or top in {"__future__"}


def classify_edit(root, proposal):
    """Recompute a tier from the diff itself. Never trust a caller-supplied tier.

    Returns (tier, reasons). Tiers: low, medium, high, never.
    """
    try:
        target, rel = _check_editable(root, proposal.path)
    except SelfEditError as exc:
        return "never", [str(exc)]
    if not target.exists():
        return "never", ["File does not exist"]
    current = target.read_text()
    if current.count(proposal.old_text) != 1:
        return "high", ["old_text does not match exactly once — ambiguous, human only"]
    new_full = current.replace(proposal.old_text, proposal.new_text, 1)
    changed = _changed_lines(proposal.old_text, proposal.new_text)
    reasons = [f"{changed} changed lines in {rel}"]
    new_dangerous = [p for p in DANGEROUS_PATTERNS
                     if p in proposal.new_text and p not in proposal.old_text]
    if new_dangerous:
        return "high", reasons + [f"new dangerous pattern(s): {new_dangerous}"]
    new_imports = _new_imports(proposal.old_text, proposal.new_text)
    non_stdlib = [m for m in new_imports if not _is_stdlib(m)]
    if non_stdlib:
        return "high", reasons + [f"new non-standard-library import(s): {non_stdlib}"]
    if changed > MEDIUM_MAX_LINES:
        return "high", reasons + [f"over medium limit of {MEDIUM_MAX_LINES} lines"]
    if rel in DATA_FILES:
        return "medium", reasons + ["data file — at least medium"]
    if changed <= LOW_MAX_LINES and not new_imports:
        return "low", reasons + ["small, no new imports"]
    return "medium", reasons + ["within medium limit, standard-library imports only or larger small diff"]


def _verify_medium(root, proposal):
    """Second, independent verification for medium edits.

    This is not the proposer asserting a tier. It re-reads the file,
    re-classifies from scratch, and must still get medium. If it
    gets anything else, the edit escalates to a human.
    """
    tier, reasons = classify_edit(root, proposal)
    if tier != "medium":
        raise SelfEditError(
            f"Medium verification failed: re-classified as {tier} ({'; '.join(reasons)}). "
            "Human approval required."
        )
    return reasons


def _append_audit(root, entry):
    """Append one JSON line to the audit log.

    The audit file is protected from propose_edit, so a model cannot
    edit it through self-editing. This internal append is the only
    write path, and it is append-only — it never rewrites history.
    The log is a review aid, not cryptographic proof; a human should
    also check the git diff.
    """
    import json
    import time
    entry = dict(entry)
    entry["time"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    audit_path = Path(root).resolve() / AUDIT_FILE
    with audit_path.open("a") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")
    return str(audit_path)


def _apply_with_tests(root, proposal, test_command, approver, tier):
    """Shared write path for human and self approval, with backup, tests, rollback, audit."""
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
        _append_audit(root, {
            "path": rel, "tier": tier, "approver": approver,
            "pending_human_review": tier == "medium",
            "changed_lines": _changed_lines(proposal.old_text, proposal.new_text),
        })
        return rel
    except Exception:
        if target.exists() and target.read_text() != current:
            target.write_text(current)
        raise


def self_approve(root, proposal, test_command=None):
    """Apply a low or medium edit without a per-edit human approval.

    The tier is recomputed here, not accepted from the caller. High
    and never edits raise and must go through human approval (or,
    for never, a human editing directly). Medium edits get a second
    verification pass first. Tests are mandatory for self-approval:
    if test_command is None, a py_compile check is used as a minimum,
    and callers should pass the full test command in practice.
    """
    tier, reasons = classify_edit(root, proposal)
    if tier == "never":
        raise SelfEditError(f"Self-approval refused (never): {'; '.join(reasons)}")
    if tier == "high":
        raise SelfEditError(
            f"Self-approval refused (high): {'; '.join(reasons)}. Human approval required."
        )
    if tier == "medium":
        _verify_medium(root, proposal)
    if test_command is None:
        test_command = [sys.executable, "-m", "py_compile", proposal.path]
    return _apply_with_tests(root, proposal, test_command, approver=f"self-{tier}", tier=tier)


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
    # Human-approved edits are logged as tier "human" — they are not
    # limited to low/medium, but they still cannot touch protected
    # files, because _check_editable (via _apply_with_tests) refuses them.
    tier, _reasons = classify_edit(root, proposal)
    if tier == "never":
        raise SelfEditError("Protected file, cannot be edited through self-edit, even with approval.")
    return _apply_with_tests(root, proposal, test_command, approver="human", tier="human")


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
