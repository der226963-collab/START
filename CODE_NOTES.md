# Code update notes

Notes are added with every code update, as requested 2026-11-04.
Each entry: what changed, why, files, and how it was tested.
Nothing here is a claim about a model being past toy-level;
loss and generation are reported separately, from actual runs.

## 2026-11-04 — CPU-portable scaling pieces (pushed, commit 68996f91)

- Muon optimizer (`mini_ai/gpt/muon.py`): Newton-Schulz
  orthogonalization, hidden 2D weights only, AdamW for
  embeddings/head/norms. CPU-friendly; no GPU-only kernels.
- QK-norm (`mini_ai/gpt/model_modern.py`, `--qk-norm`):
  RMSNorm on Q and K per head. Off by default, so old
  checkpoints still load.
- Trapezoidal LR schedule (`train_gpt.py`, `--lr-schedule
  trapezoid`): 5% warmup, plateau to 80%, decay to 10%.
- Gradient accumulation (`train_gpt.py`, `--grad-accum`):
  effective batch = batch x accum.
- Tested: 4 new tests in `tests/test_scaling.py`, plus a
  20-step run with all four flags together (val 4.53 -> 3.58).
  Full suite 44 tests OK in both python envs.

## 2026-11-04 — Best-checkpoint save fix

- `train_gpt.py` used to save a checkpoint only at the end,
  so a runtime restart lost a 1h15m run with nothing saved.
- Now it saves the best checkpoint immediately on each val
  improvement (every 50 steps). Tested with a 10-step run.
- Note, pre-existing and unrelated: the char-tokenizer final
  JSON write crashed in that test (see next entry); BPE runs
  were not affected.

## 2026-11-04 — Code-improvement batch (this batch)

Bugs fixed, with the audit finding that motivated each one:
1. Char checkpoint JSON (`train_gpt.py`): `getattr(tokenizer,
   "chars", tokenizer.vocab)` evaluated the default eagerly
   and crashed on char tokenizers. Fixed to `None` default.
2. QK-norm / tie-weights checkpoint loading
   (`evaluate_gpt.py`, `generate_gpt.py`): both now pass
   `meta.get("qk_norm", False)` and `meta.get("tie_weights",
   False)` through, so a checkpoint trained with those
   flags loads instead of failing on unexpected keys.
3. Validation split (`train_gpt.py`): was the last 10% of
   concatenated text (mostly the last book). Now 90/10
   within each file, so every book is in both splits.
   Cached token runs use the flat 90/10 split of the
   cached stream, and say so in code — that limitation is
   documented, not hidden.
4. Agent retrieval (`mini_ai/agent.py`): now excludes
   `data/expanded_corpus.txt`, which at 19M chars made
   every retrieval scan the whole assembled corpus and
   return assembled passages instead of source files.

Performance, in the order they matter:
5. Token cache (`train_gpt.py`, `--token-cache`): BPE
   training + encoding of 19M chars was the slowest part
   of a run. A cache file stores token ids + tokenizer
   JSON; a repeat run loads it instead of re-tokenizing.
   Cache is keyed by path only — delete it after changing
   the corpus, or pass a new path. This is stated in code.
6. Weight tying (`model.py`, `model_modern.py`,
   `--tie-weights`): output head shares the token embedding
   storage. Off by default for checkpoint compatibility.
7. Fused attention (`model.py`, `model_modern.py`):
   manual scores/mask replaced with
   `F.scaled_dot_product_attention(is_causal=True)`.
   Same causal math, fused kernel, faster on CPU too.
   The old mask buffer is kept but no longer used.

Smaller improvements:
8. Fetcher licences (`mini_ai/data_fetch.py`): added
   "CC BY-NC-SA 3.0", because books already approved under
   3.0 (Downey; Statics GeoGebra content) were refused by
   the fetcher, which only listed 4.0. This is a direct
   human edit to a protected file, with this note as the
   commit-message record.
9. Wikipedia plain text (`mini_ai/data_fetch.py`):
   article URLs now try the Wikipedia API extracts
   endpoint first (same allowlisted host, same CC BY-SA
   licence), falling back to HTML stripping if no extract
   is returned. This is the fix for the nav/menu text in
   the Climate and Renewable files.
10. Evaluation reproducibility (`evaluate_gpt.py`,
    `--seed`, default 42): evaluation batches were random
    with no seed, so two runs gave different losses.
11. Muon LR (`train_gpt.py`, `--muon-lr`): an explicit
    override, defaulting to `--lr`. Published Muon range
    is 0.02-0.05, but it is NOT raised blindly here —
    a higher value must be chosen explicitly.

Tests for this batch: `tests/test_improvements.py`
(weight tying, SDPA forward, retrieval exclusion,
fetcher licence + Wikipedia parsing, per-file split rule).
Full suite must be 44+ tests OK in both python envs
before pushing; a flaky torch run is re-run, not ignored.
