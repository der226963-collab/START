"""Evaluate a LoRA fine-tuned SmolLM2 on the task it was trained for.

Loads the base model + a LoRA adapter checkpoint, then for each
example in a JSONL file (the val split by default) formats the
prompt as "### Instruction:\n{instruction}\n### Response:\n" and
generates a completion. Prints the prompt, the expected response,
and the model's actual completion, so a human can judge whether
the model learned the intent / instruction behaviour.

Also reports an exact-match rate (completion starts with the
expected response, ignoring trailing whitespace) as a rough
signal -- a low rate does not by itself mean failure, since a
good paraphrase scores 0 here; read the outputs.

Usage:
  python evaluate_smollm2_finetune.py --adapter checkpoints/smollm2-lora-mix/checkpoint.pt
  python evaluate_smollm2_finetune.py --adapter ... --data data/finetune/smollm2-mix-train.jsonl --limit 6
"""
import argparse
import json
from pathlib import Path

import torch

from mini_ai.gpt.lora import apply_adapter_checkpoint
from mini_ai.gpt.smollm2 import load_pretrained, load_tokenizer

DEFAULT_DIR = "/home/hatch/workspace/models/smollm2-360m"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", default=DEFAULT_DIR)
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--data", default="data/finetune/smollm2-mix-val.jsonl")
    ap.add_argument("--limit", type=int, default=0, help="0 = all")
    ap.add_argument("--max-new", type=int, default=120)
    ap.add_argument("--temperature", type=float, default=0.0,
                    help="0 = greedy (deterministic), the right choice "
                         "for checking whether the model learned a response")
    ap.add_argument("--max-context", type=int, default=512)
    args = ap.parse_args()

    model, config = load_pretrained(args.model_dir, dtype=torch.bfloat16)
    apply_adapter_checkpoint(model, args.adapter)
    tokenizer = load_tokenizer(args.model_dir)
    model.eval()

    rows = [json.loads(l) for l in Path(args.data).read_text().splitlines() if l.strip()]
    if args.limit:
        rows = rows[:args.limit]

    exact = 0
    for i, row in enumerate(rows):
        prompt = f"### Instruction:\n{row['instruction']}\n### Response:\n"
        ids = tokenizer.encode(prompt, add_special_tokens=False).ids
        idx = torch.tensor([ids], dtype=torch.long)
        with torch.no_grad():
            out = model.generate(idx, max_new_tokens=args.max_new,
                                 temperature=args.temperature,
                                 eos_id=config.eos_token_id,
                                 max_context=args.max_context)
        full = tokenizer.decode(out[0].tolist(), skip_special_tokens=True)
        completion = full[len(prompt):].strip()
        expected = row["response"].strip()
        # Exact means the completion starts with the expected
        # response (the docstring's definition). A truncated
        # completion must NOT count: expected.startswith(completion)
        # would score a prefix of the answer as exact.
        is_exact = bool(completion) and completion.startswith(expected)
        if is_exact:
            exact += 1
        print(f"--- [{i + 1}/{len(rows)}] source={row['source']} "
              f"exact={'YES' if is_exact else 'no'}")
        print(f"Q: {row['instruction']}")
        print(f"expected: {expected[:300]}")
        print(f"got:      {completion[:300]}")
        print()
    print(f"exact-match: {exact}/{len(rows)}")


if __name__ == "__main__":
    main()
