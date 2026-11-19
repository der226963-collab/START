"""Batch generation pack for the min-new-tokens seed-7 reseed check (2026-11-19).

Same as tools/gen_pack_minlen20_rep12.py, but with seed 7 (the original
min_new_tokens numbers were all seed 42) and support for v7 and v13, so the
12/12 vs 11/12 leg-4-protocol counts at temp 0.7 can be tested against
sampling luck. Temp 0.7 only (the bar's leg-4 temperature; temp 0 is
argmax, so a reseed there would be byte-identical). The shared driver
was not modified.

Runs the 12 fixed release-pack prompts in eval/heldout_prompts.txt
for the SmolLM2 v13 and v7 LoRA adapters at temperature 0.7 or
0.0, length 150, with a repetition penalty (default 1.2) and a
minimum of 20 new tokens before EOS may be generated
(min_new_tokens=20, see SmolLM2Model.generate).

Same pattern as tools/gen_pack_rep12_v13.py: loads each adapter
once and runs the identical computation per prompt (same
load_pretrained BF16, same apply_adapter_checkpoint, same
tokenizer.encode(prompt, add_special_tokens=False), same
model.generate(idx, max_new_tokens=150, temperature, eos_id,
max_context=1024, repetition_penalty, min_new_tokens), same
decode). Seeding matches the baseline packs: temp 0.7 seeds once
before loading; temp 0 seeds before loading and before each
generation — temp 0 is argmax, so the seed does not change the
output.

Resumable: each prompt's output is written to its dated file as
soon as it finishes, and existing files are skipped on re-run, so
an interruption loses only the prompt in flight.

Usage (from workspace/ai-starter, with ~/workspace/torch-venv/bin/python):
  python tools/gen_pack_minlen20_rep12_seed7.py --adapter v13 --temperature 0.7
  python tools/gen_pack_minlen20_rep12_seed7.py --adapter v7 --temperature 0.7
Outputs (local only, never pushed):
  eval/smollm2-lora-{v13,v7}-gen-minlen20-rep12-seed7-2026-11-19-NN.txt
Progress log: eval/gen-minlen20-rep12-seed7-2026-11-19.log
"""
import argparse
import re
import sys
import time
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mini_ai.gpt.lora import apply_adapter_checkpoint  # noqa: E402
from mini_ai.gpt.smollm2 import load_pretrained, load_tokenizer  # noqa: E402

MODEL_DIR = "/home/hatch/workspace/models/smollm2-360m"
ADAPTERS = {
    "v7": ROOT / "checkpoints/smollm2-lora-mix-v7/checkpoint.pt",
    "v13": ROOT / "checkpoints/smollm2-lora-mix-v13/checkpoint.pt",
}
DATE = "2026-11-19"
SEED = 7
MIN_NEW_TOKENS = 20


def parse_prompts():
    text = (ROOT / "eval/heldout_prompts.txt").read_text()
    section = text.split("## Prompts", 1)[1]
    prompts = []
    for line in section.splitlines():
        m = re.match(r"^(\d+)\.\s+(.*\S)\s*$", line)
        if m:
            prompts.append((int(m.group(1)), m.group(2)))
    prompts.sort()
    assert len(prompts) == 12, f"expected 12 prompts, got {len(prompts)}"
    return prompts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", choices=["v7", "v13"], required=True)
    ap.add_argument("--temperature", type=float, choices=[0.0, 0.7],
                    required=True)
    ap.add_argument("--penalty", type=float, default=1.2,
                    help="Repetition penalty (1.0 = off).")
    ap.add_argument("--min-new-tokens", type=int, default=MIN_NEW_TOKENS,
                    help="Minimum new tokens before EOS may be generated.")
    ap.add_argument("--only", type=int, default=None,
                    help="Run one prompt number only (smoke test).")
    ap.add_argument("--limit", type=int, default=None,
                    help="Run only the first N prompts.")
    args = ap.parse_args()

    prompts = parse_prompts()
    if args.only is not None:
        prompts = [p for p in prompts if p[0] == args.only]
    if args.limit is not None:
        prompts = prompts[: args.limit]

    tag = f"minlen{args.min_new_tokens}-rep{int(round(args.penalty * 10))}-seed7"
    temp_tag = "temp0-" if args.temperature == 0.0 else ""
    name = args.adapter
    log_path = ROOT / f"eval/gen-minlen{args.min_new_tokens}-rep12-seed7-{DATE}.log"

    torch.manual_seed(SEED)
    t0 = time.time()
    model, config = load_pretrained(MODEL_DIR, dtype=torch.bfloat16)
    apply_adapter_checkpoint(model, str(ADAPTERS[name]))
    tokenizer = load_tokenizer(MODEL_DIR)
    with log_path.open("a") as log:
        log.write(f"[{time.strftime('%H:%M:%S')}] {name} temp "
                  f"{args.temperature} penalty {args.penalty} "
                  f"min_new_tokens {args.min_new_tokens} loaded in "
                  f"{time.time() - t0:.0f}s (seed {SEED})\n")
        log.flush()
    for num, prompt in prompts:
        out_path = (ROOT / "eval" /
                    f"smollm2-lora-{name}-gen-{temp_tag}{tag}-{DATE}-{num:02d}.txt")
        if out_path.exists():
            print(f"{name} temp {args.temperature} prompt {num}: exists, skipping",
                  flush=True)
            continue
        if args.temperature == 0.0:
            torch.manual_seed(SEED)
        t1 = time.time()
        ids = tokenizer.encode(prompt, add_special_tokens=False).ids
        idx = torch.tensor([ids], dtype=torch.long)
        out = model.generate(idx, max_new_tokens=150,
                             temperature=args.temperature,
                             eos_id=config.eos_token_id,
                             max_context=1024,
                             repetition_penalty=args.penalty,
                             min_new_tokens=args.min_new_tokens)
        text = tokenizer.decode(out[0].tolist(), skip_special_tokens=True)
        out_path.write_text(text)
        msg = (f"{name} temp {args.temperature} prompt {num}: wrote "
               f"{out_path.name} ({len(text)} chars, {time.time() - t1:.0f}s)")
        print(msg, flush=True)
        with log_path.open("a") as log:
            log.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
            log.flush()
    print(f"{name} temp {args.temperature} done in {time.time() - t0:.0f}s",
          flush=True)


if __name__ == "__main__":
    main()
