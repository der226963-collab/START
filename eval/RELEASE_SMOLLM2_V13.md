# SmolLM2 v13 release (START)

Released 2026-11-19. v13 is the first adapter to pass all five legs of
the release bar (`eval/RELEASE_BAR_SMOLLM2.md`), and the release
candidate under it. The release is the whole model including general
English — not a from-scratch model: the base is the external
SmolLM2-360M (HuggingFaceTB, Apache 2.0, 361,821,120 parameters), and
its weights are not included in this release. This release supersedes
v7 as START's released SmolLM2 adapter.

## Training

- Trained from the SmolLM2-360M base on
  `data/finetune/smollm2-rag-v12-train.jsonl` as-is: 188 rows
  (sha256
  `df3995491eb3a7b2449acc40aa8f8441b6d9c2065dc810e81e7e77f3173fce72`)
  — v9's 169 rows verbatim plus 19 plain-narrative replay rows from
  Darwin's *On the Origin of Species*, First Edition 1859 (public
  domain). Full build provenance in
  `data/finetune/smollm2-rag-v12-train.jsonl.json` (builder
  `tools/build_v12_data.py`).
- Recipe: LoRA rank 16, alpha 32, LR 1e-4, 12 epochs, AdamW, batch 2,
  grad-accum 2, seed 42. 564 planned steps, one resume from step-475
  after an interruption; final trainer val loss 0.0082.
- Code: `train_smollm2_lora.py`, `mini_ai/gpt/lora.py`; generation in
  `mini_ai/gpt/smollm2.py` with `--min-new-tokens`,
  `--repetition-penalty` and `--no-repeat-ngram` flags.

## Eval numbers (fixed release-eval pack)

- Pinned val: **8/8** (`data/finetune/smollm2-rag-v9-val.jsonl`,
  sha256
  `2743e47db57becb966d487b00d1324a013d0eabb2cf8cea9c878dc0003dab5e0`).
- Fresh-paraphrase probe: **8/8** (score only; the probe set itself
  stays local so it remains a held-out test).
- General held-out loss: **3.2812** (ppl 26.6) on
  `eval/heldout_text.txt`; bar < 3.34. Base reference 2.7633.
- Generation, leg-4 protocol (temp 0.7, length 150,
  `--repetition-penalty 1.2`, `--min-new-tokens 20`): **12/12**
  coherent at seed 42 (lenient count, the leg metric; strict 10/12).
  Penalty-only history: 9/12 at seed 42 and 10/12 at seed 7, before
  min_new_tokens was adopted into the protocol. Outputs in
  `eval/smollm2-lora-v13-gen-*.txt` (three 12-prompt sets: penalty-only
  seed 42, penalty-only seed 7, amended protocol seed 42).
- Intent checks: **8/8**.

## Not included in this release

- The adapter checkpoint (~39.6 MB) — train it from the base with the
  files above to reproduce it.
- The SmolLM2 base weights (external; see the model card).
- The fresh-paraphrase probe set and probe eval reports.
