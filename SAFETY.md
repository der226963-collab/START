# Safety rules for this project — protected file

This file is protected by `mini_ai/self_edit.py`. A model using
self-editing cannot edit this file, cannot edit `self_edit.py`,
cannot edit `.gitignore`, and cannot edit the guardrail tests in
`tests/test_self_edit.py`. A human edits those files directly, in
an editor, with a commit message saying so.

## The rules, in plain language

1. **A human approves every code change.** A model proposes a diff.
   Nothing is written until a human has read that diff and approved
   it. The model cannot approve its own edit, and there is no
   approved-by-default path in the code.
2. **Guardrails cannot be edited by the model.** That includes:
   - its own approval code (`mini_ai/self_edit.py`)
   - these safety rules (`SAFETY.md`)
   - the list of what is ignored / hidden (`.gitignore`)
   - the tests that check the guardrails (`tests/test_self_edit.py`)
3. **Tests must pass, or the change rolls back.** An approved edit
   that breaks tests is automatically reverted to the previous
   version. A backup is kept for manual revert at any time.
4. **Edits stay inside this project.** No paths outside the project
   root, no symlink escapes, no secrets, no checkpoints, no
   credentials. Only `.py`, `.md`, and `.txt` files.
5. **Layers stay separate.** A language model drafts and summarises.
   It does not allocate food, energy, housing, or care, and it does
   not decide. People in assembly decide; a separate planning
   calculation checks whether a plan fits hard limits.
6. **Shutdown and rollback do not depend on the model.** A human can
   stop the process, delete a checkpoint, and restore a backup
   without the model's cooperation.

## Why

This follows PCAC's safety charter: corrigibility first, human
assemblies as decider, transparency (a diff is an audit trail),
and evaluability. A cooperative AI that people cannot inspect,
challenge, or stop is not a cooperative AI, no matter how good
its outputs look.

## Changing these rules

Only a human, directly, in an editor, with a clear commit message.
Never through a model-generated self-edit, never by editing the
guardrail code to remove itself, and never silently.
