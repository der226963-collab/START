#!/usr/bin/env python3
"""Score min_new_tokens=20 sets vs rep12 baselines: prompt-stripped continuation
lengths, means, and immediate-EOS counts. Prompts from eval/heldout_prompts.txt
lines 40-51 (the 'N. ' prefix is not in the generation files)."""
import glob
import os
import statistics

EVAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "eval")
PROMPTS = []
with open(os.path.join(EVAL, "heldout_prompts.txt")) as f:
    lines = f.read().splitlines()
for line in lines[39:51]:
    n, text = line.split(". ", 1)
    PROMPTS.append(text)

SETS = [
    ("v13 temp0 BASELINE", "smollm2-lora-v13-gen-temp0-rep12-2026-11-19-%02d.txt"),
    ("v13 temp0 MINLEN20", "smollm2-lora-v13-gen-temp0-minlen20-rep12-2026-11-19-%02d.txt"),
    ("v13 temp0.7 BASELINE", "smollm2-lora-v13-gen-rep12-2026-11-19-%02d.txt"),
    ("v13 temp0.7 MINLEN20", "smollm2-lora-v13-gen-minlen20-rep12-2026-11-19-%02d.txt"),
    ("v7 temp0 BASELINE", "smollm2-lora-v7-gen-temp0-rep12-2026-11-18-%02d.txt"),
    ("v7 temp0 MINLEN20", "smollm2-lora-v7-gen-temp0-minlen20-rep12-2026-11-19-%02d.txt"),
    ("v7 temp0.7 BASELINE", "smollm2-lora-v7-gen-rep12-2026-11-18-%02d.txt"),
    ("v7 temp0.7 MINLEN20", "smollm2-lora-v7-gen-minlen20-rep12-2026-11-19-%02d.txt"),
    ("v11 temp0 BASELINE", "smollm2-lora-v11-gen-temp0-rep12-2026-11-18-%02d.txt"),
    ("v11 temp0 MINLEN20", "smollm2-lora-v11-gen-temp0-minlen20-rep12-2026-11-19-%02d.txt"),
]

for name, pat in SETS:
    lens, eos = [], []
    for i, prompt in enumerate(PROMPTS, 1):
        path = os.path.join(EVAL, pat % i)
        if not os.path.exists(path):
            print(f"{name}: MISSING {path}")
            continue
        text = open(path, encoding="utf-8").read()
        assert text.startswith(prompt), f"{name} P{i}: file does not start with prompt"
        cont = text[len(prompt):].strip()
        lens.append(len(cont))
        if len(cont) == 0:
            eos.append(i)
    print(f"{name}: n={len(lens)} mean={statistics.mean(lens):.1f} median={statistics.median(lens):.0f} "
          f"min={min(lens)} max={max(lens)} EOS={eos if eos else 'none'}")
    print(f"   per-prompt continuation lengths: {lens}")
