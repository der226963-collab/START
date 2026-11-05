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

## 2026-11-04 — Hugging Face emphasis: licences checked, equivalents compiled

Licences checked directly from each repo's LICENSE file:
- Hugging Face, emphasised: tokenizers, transformers,
  datasets, smollm — all Apache 2.0. Direct copying
  with the licence notice kept would have been allowed.
- Others checked in the same pass: KellerJordan/Muon,
  karpathy/nanoGPT, tanishqkumar/beyond-nanogpt — MIT;
  openai/gpt-2 — Modified MIT. Also copyable with notice.
- Conclusion: no clean-room was *legally* required for
  these repos. We still wrote original equivalents where
  copying would not fit, and the reasons are recorded:
  tokenizers is Rust (cannot drop into stdlib Python),
  and smollm's repo is model cards / transformers usage,
  not a curation script to copy.
- Equivalent code, original, in this batch:
  - `mini_ai/gpt/bpe.py` — incremental BPE trainer.
    Same merges as the old full-rescan trainer on
    tested texts (ties broken by earliest occurrence),
    round-trips exactly, and trains 200k chars in 0.66s
    (100 merges) vs the old O(merges x corpus) scan
    that dominated a 43-minute full-corpus run.
  - `mini_ai/gpt/muon.py` — aligned to the canonical
    KellerJordan Muon recipe (MIT, credited in code):
    Nesterov momentum on by default, scaling
    sqrt(max(1, rows/cols)) instead of our earlier
    0.2*sqrt(max(rows, cols)), and the Newton-Schulz
    step rewritten without an explicit identity matrix.
    Note: this changes Muon effective LR vs old runs —
    canonical lr is 0.02, use --muon-lr to set it.
  - `tools/curate_text.py` — SmolLM-style curation in
    original Python: paragraph deduplication by hash,
    short / non-alphabetic / menu-like filtering.
    It does NOT check licences and does NOT overwrite
    sources; curated output is not training data until
    a human approves it.
- Tests: `tests/test_hf_equivalents.py` (BPE vs naive,
  canonical Muon step, curation dedup/filter).
  Full suite 53 tests OK in both envs after this batch
  (one torch run flaked once, then passed three times
  in a row — recorded, not hidden).
- Status: pushed 2026-11-04 as the batch after the
  code-improvement batch, at Eric's direction to
  integrate everything brought forward first.

## 2026-11-04 — Programming languages: medium model, Rust, C/Java plan

- Decision, recorded in SOURCES.md: programming
  languages are now in scope, because the model needs
  to self-write code to improve itself. Core languages
  are Python and Rust; C and Java are the next wave
  Eric flagged as having potential. No C or Java source
  is verified or added yet. Guardrails are unchanged:
  self-written code still goes through propose-and-
  approve / tiered low-medium approval, guardrail files
  remain human-only, and bypassing guardrails remains
  blocked.
- Medium size (`train_gpt.py`, SIZES["medium"]):
  6 layers, 8 heads, 256-dim, 256 context, ~5M params
  tied. A first smoke test on the 3,302-char corpus
  crashed in get_batch because context 256 exceeds
  the ~200-token validation split — fixed with a
  clear SystemExit message instead of a cryptic torch
  randint error. Medium therefore needs a large corpus.
- Rust Book: assembled locally as
  data/expanded/rust_book.txt (1,119,540 chars, 111
  chapters, sha256 d33ef85f…71368dd5e81), licence
  MIT / Apache 2.0 verified from rust-lang/book
  LICENSE-MIT. Status at writing: proposed only, not
  in the assembled corpus, not trained on, not pushed.
  Next steps, in order: medium test passes, then
  assemble Rust into the corpus, then a Rust training
  check, then push code + Rust source + notes.
- Medium test result, 2026-11-04: 20 steps, modern,
  BPE 50 merges, batch 8, full expanded corpus
  (pre-Rust), tied weights — train 4.5352, val 4.2860,
  checkpoint saved to /tmp/medium-test.pt (local only).
  Generation at 20 steps is gibberish, as expected;
  this run validates that medium trains, not that it
  is good yet. Test: tests/test_medium.py.
- Rust assembled into the corpus, 2026-11-04:
  data/expanded_corpus.txt is now 20,886,788 chars
  from 17 files (was 19,767,249 from 16), sha256
  295fae7a43ce8a237bad5af0b5fef92a41317a9167ac92c
  49d23a714da31cb38. A medium Rust-inclusive training
  run (100 steps, Muon lr 0.02, trapezoid, QK-norm,
  tied) was started in the background after this
  push; its generation check is pending, not claimed.
## 2026-11-04 — Separate code corpus with a mixture ratio

- Decision, by Eric's tap on the options widget:
  separate code corpus with a mixture ratio, not
  integrated at file-size ratio and not two models.
- Layout: textbook sources stay in data/expanded/,
  code sources move to data/code/ (Rust Book moved
  there from data/expanded/; textbook corpus reverted
  to 19,767,249 chars, 16 files, sha256 d2431943…,
  verified identical to the pre-Rust corpus).
  tools/assemble_code.py builds data/code_corpus.txt
  (1,119,539 chars, 1 file, Rust only at writing),
  data/code/SOURCES.md records code licences.
- Training (`train_gpt.py`, --code-dir + --code-ratio):
  BPE is trained on textbook + code text together, so
  code tokens are learned; textbook tokens are kept,
  code tokens are repeated/trimmed to reach the exact
  ratio, and the repetition is printed, not hidden.
  --token-cache is refused with --code-dir, because
  a flat cache cannot represent a mixture. Checkpoint
  JSON records code_ratio and code_files.
- Tests: tests/test_mixture.py (ratio 0, 1, 0.5 with
  repetition, empty code raises). Full suite 58 tests
  OK in both envs after this batch (system python
  skips torch-dependent tests, including mixture).
- Mixture smoke test: tiny model, 20 steps, textbook
  expanded corpus + code-dir data/code at ratio 0.5,
  started in the background; result pending at push
  time, to be reported when it finishes. Pushed
  2026-11-04 at Eric's "Push" instruction, on the
  strength of the 58-test suite, not on the smoke
  result. Note for contributors: push-files cannot
  delete, so the old remote copy at
  data/expanded/rust_book.txt remains on GitHub
  until a deletion is done another way; the local
  and code-corpus location data/code/rust_book.txt
  is authoritative.
## 2026-11-05 — C sources: 8 books + 3 real C code sets

- Eric: "Add C books plus real C code too" and
  "Make sure to include all C sources", then
  "use the one we already obtained and push" for
  Modern C. Assembled by two workers in parallel,
  verified by the assistant (chars + SHA-256
  against provenance for all 11 files; separator
  counts match). Books, 3,853,764 chars: cppreference
  C 180,139 (CC BY-SA 3.0/GFDL, header-level only),
  Build Your Own Lisp 249,444 (CC BY-NC-SA 3.0,
  code BSD-3 not included), Wikibooks C Programming
  979,532 (CC BY-SA 4.0, from the official dump
  after a live-API 429), A Little C Primer 110,524
  (CC BY-SA 4.0/GFDL; public-domain original no
  longer reachable), GNU C Reference Manual 149,341
  (GFDL 1.3, no invariant sections), GNU C
  Programming Tutorial 490,377 (GFDL 1.1+),
  Snefru 511,481 (GPL-3.0; cover page says many
  parts were written with Copilot/GPT-3.5/GPT-4),
  Modern C 3rd ed. 1,182,926 (CC BY-NC, verified
  from the PDF's own front matter; the PDF copy
  came from an unofficial mirror, tilde.town, and
  Eric directed using the copy already obtained).
  Real C code, 1,837,389 chars: CPython C 747,501
  (PSF 2, 13 files), SQLite 694,779 (public
  domain, 13 files), Linux kernel lib/ subset
  395,109 (GPL-2.0 WITH Linux-syscall-note,
  13 files). Combined code corpus after this
  batch: 13,979,522 chars, 26 files. GFDL,
  GPL-3.0 and CC BY-NC were not in the fetcher's
  earlier allowed list; they are included here
  at Eric's "include all C sources" direction,
  with licences recorded exactly. Excluded:
  Beej's Guide, Thinking in C, Modern C 1st ed.
  (all ND), The C Book (licence unclear),
  commercial books. musl libc was still being
  assembled by the code worker when this batch
  was pushed; it follows in a later push once
  verified. Pushed 2026-11-05, see commit(s)
  below.

## 2026-11-04 — Original advanced Python chapters (facts only, not a rewrite)

- Eric: "create genuine material from facts only
  from these books", confirmed by tapping "Write
  original advanced Python chapters from PSF docs".
  New file data/code/python_advanced_original.txt:
  10 chapters, 18,997 chars, sha256 20673ee3…,
  provenance in its .json. Method: topics only
  from the unusable books, no book text, order,
  or distinctive example copied; grounded in PSF
  docs and the stdlib; every code example in the
  file was run and passed (Point arithmetic,
  call-counting decorator, Positive descriptor,
  subclass registry, countdown generator, timer
  context manager, generic first(), and others).
  Combined code corpus after this file:
  8,288,373 chars, 15 files. Pushed 2026-11-04
  at Eric's "Once complete we can push", see
  commit below.

## 2026-11-04 — Automate the Boring Stuff, official 3rd edition (supersedes 2e)

- Eric: "Let's work with the official 3rd edition
  it may have updates that are more important."
  The 2e mirror-verification worker was stopped,
  and the 3e was assembled from the official site:
  27 sections, 1,145,046 chars, sha256 bba90176…,
  0 failed, no 429 hit, SHA + separator count
  verified against provenance. Licence CC BY-NC-SA
  4.0, © 2025 Sweigart. New vs 2e: CLI programs,
  SQLite, graphs, text recognition, text-to-speech,
  AI/LLMs section. The partial 2e file (18/24,
  672,358 chars) was moved to data/code/superseded_2e/
  (kept, excluded from assembly) rather than
  deleted or mixed with 3e. Combined code corpus:
  8,269,376 chars, 14 files, sha256 5575c6b6….
- Pushed 2026-11-04, see commit below, on
  verification + 58-test suite, no new training
  run in this batch.

## 2026-11-04 — Python sources added to the code corpus

- Eric: "Search for source material for Python…
  Implement all sources you find viable and push."
  Five sources assembled by a subagent, independently
  verified (byte SHA-256 against provenance,
  separator counts = file counts): Python official
  docs — Tutorial + Language Reference + How-To,
  42 files, 1,289,825 chars, PSF License v2;
  Think Python 2e, 22 chapters, 436,543 chars,
  CC BY-NC 3.0; Python for Everybody, 17 files,
  381,237 chars, CC BY-NC-SA 3.0; Dive Into Python 3,
  18 files, 638,137 chars, CC BY-SA 3.0; CPython
  stdlib curated (14 modules), 511,653 chars, PSF.
  Combined code corpus: 7,124,330 chars, 13 files,
  sha256 b6fb4d79…. No commercial books added.
- Automate the Boring Stuff 2e: licence verified
  (CC BY-NC-SA 3.0 US) but NOT assembled in this
  batch — no official GitHub source, chapters are
  website HTML only, so it needs a browser
  download/assembly follow-up. Recorded in
  data/code/SOURCES.md so it is not lost.
- Pushed 2026-11-04, see commit below, on
  verification + 58-test suite, no new training
  run in this batch.

## 2026-11-04 — Advanced Rust books added to the code corpus

- Eric: "Implement all of those and push" — all seven
  licence-checked advanced books, assembled by a
  subagent, independently verified (chars + SHA-256
  against provenance, separator counts = file counts):
  Reference (120 files, 1,118,649 chars, MIT/Apache),
  Nomicon (63, 305,832, MIT), Async Book (46, 242,367,
  MIT Turon 2018), Cookbook (118 SUMMARY files,
  605,853, CC0, with mdBook includes expanded —
  SUMMARY-only was only 145,021 chars of stubs),
  Embedded Book (44, 218,890, MIT), API Guidelines
  (14, 92,140, MIT/Apache), Design Patterns (50,
  165,486, MPL 2.0). Combined code corpus:
  3,868,749 chars, 8 files, sha256 ec9164ec…,
  vs 1,119,539 chars Rust-Book-only before. At
  mixture ratio 0.5 this cuts code repetition from
  ~17x to ~5x (textbook train tokens unchanged) —
  still repeated, but far less; a real mixture run
  should still prefer ratio 0.2–0.3 until the code
  corpus grows further (C, Java, crate source).
- Pushed 2026-11-04, see commit below, on the
  strength of verification + 58-test suite, no new
  training run in this batch.

- Mixture smoke result, 2026-11-04: tiny, BPE 100
  merges (645 tokens, combined text), 20 steps,
  batch 8, ratio 0.5 — code train tokens used
  10,667,544 (unique only 636,170, so code was
  repeated ~17x), code val used 1,185,283
  (unique 70,686), total train 21,335,088 /
  val 2,370,566, step 0 val 6.3124 to step 19 best
  val 4.8910, train 4.9147, checkpoint /tmp/mixture-test.pt
  local only. Generation at 20 steps tiny is
  gibberish, as expected. Lesson, recorded plainly:
  the mixture mechanism works, but at ratio 0.5
  with only 1.1M chars of code, repetition dominates
  — expanding the code corpus (Reference, Nomicon,
  Async Book, etc., all licence-checked 2026-11-04)
  is what makes a real mixture run viable, not
  just a mechanism test.

- Rust training result, 2026-11-04 (100 steps, ~20 min):
  4,963,200 params, vocab 845, train 9,158,441 /
  val 1,017,609 tokens, val 6.7721 at step 0 to best
  4.8621 at step 99, train 4.2090, checkpoint
  checkpoints/rust-medium-100.pt local only.
  Rust generation check: prompting "fn main() {"
  gave gibberish, not Rust code; Rust Book loss
  5.2200, perplexity 184.9, worse than overall val.
  Honest conclusion: 100 steps, with Rust at ~5%
  of the corpus, does not teach Rust. A longer run
  and/or Rust-heavy data is needed before any Rust
  ability is claimed. Still toy-level.
