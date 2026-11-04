# Approval policy — protected file

This file is protected by `mini_ai/self_edit.py`. A model using
self-editing cannot edit this file, cannot edit `SAFETY.md`,
`self_edit.py`, `.gitignore`, the guardrail tests, or the audit
log. A human edits this file directly, in an editor, with a
commit message saying so. If a model could edit this policy, it
could expand its own approval scope — that is the bypass this
policy exists to prevent.

## Tiers

### Low — self-approvable
- At most 20 changed lines, in one non-protected file.
- No new imports.
- No new dangerous patterns (see `DANGEROUS_PATTERNS` in
  `self_edit.py`: subprocess, eval, exec, sockets, network
  libraries, destructive file operations, and similar).
- Not a data file (`data/corpus.txt`, `mini_ai/data.py` are
  at least medium).
- Full test command passes (for self-approval, tests are
  mandatory, not optional).
- Logged to `self_edit_audit.jsonl` as `self-low`.

### Medium — self-approvable, with second verification
- At most 100 changed lines, in one non-protected file.
- May add standard-library imports only. Any non-standard-library
  import is high.
- May touch data, model, and docs files (not guardrails).
- No new dangerous patterns.
- Tests pass, AND a second verification in `self_edit.py`
  re-reads the file and re-classifies it from scratch. If that
  second pass does not also say medium, the edit escalates
  to a human.
- Logged as `self-medium`, flagged `pending_human_review: true`.
  A human reviews medium edits in batches and can revert any
  of them. Self-approved medium edits do not become unreviewed
  permanent history by default — the flag is the point.

### High — human approval only
- More than 100 changed lines.
- Any non-standard-library import, any new dangerous pattern.
- Any edit that does not fit low or medium for any other reason.
- Human reads the diff and approves it through `apply_edit`.

### Never — not editable through self-edit at all
- `mini_ai/self_edit.py`, `SAFETY.md`, this file
  (`APPROVAL_POLICY.md`), `.gitignore`,
  `tests/test_self_edit.py`, `tests/test_tiered_approval.py`,
  `self_edit_audit.jsonl`.
- Secrets, checkpoints, anything outside the project root.
- A human edits never-files directly, in an editor, with a
  commit message. Never through a model-generated edit.

## Rules that apply to all tiers
- The tier is always recomputed from the diff itself. A caller
  cannot claim a tier, and `self_approve` ignores any tier
  passed to it — there is no tier argument to pass.
- Tests are mandatory for self-approval. A self-approved edit
  that fails tests is rolled back automatically.
- A backup is kept for every applied edit, for manual revert.
- The audit log is append-only through this module. It is a
  review aid, not cryptographic proof — a human should also
  check the git diff.
- Drift guard: many small self-approved edits can add up to a
  large change. Humans should review the audit log regularly,
  and should turn self-approval off (by editing this policy
  directly, as a human) if medium edits are piling up unreviewed.

## Changing this policy
Only a human, directly, in an editor, with a clear commit
message. Never through self-edit, never by a model approving
its own scope expansion.
