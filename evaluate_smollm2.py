"""Evaluate SmolLM2-360M on a text file (held-out loss + perplexity).

Same metric and batching as evaluate_gpt.py so the numbers compare
directly with the MiniGPT evals: random batches, seed 42, batch 32,
context 512 by default. The model runs in BF16 (its native dtype)
unless --dtype fp32 is given.

Usage:
  python evaluate_smollm2.py --data eval/heldout_text.txt
"""
import argparse
import math
from pathlib import Path

import torch

from mini_ai.gpt.smollm2 import load_pretrained, load_tokenizer

DEFAULT_DIR = "/home/hatch/workspace/models/smollm2-360m"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", default=DEFAULT_DIR)
    parser.add_argument("--data", required=True)
    parser.add_argument("--batches", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=32,
                        help="Sequences per batch. The MiniGPT evals used 32, "
                             "but a 360M model on this CPU needs a smaller batch "
                             "(e.g. 4) or the run times out.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--context", type=int, default=512)
    parser.add_argument("--dtype", choices=["bf16", "fp32"], default="bf16")
    args = parser.parse_args()
    torch.manual_seed(args.seed)

    dtype = torch.bfloat16 if args.dtype == "bf16" else torch.float32
    model, config = load_pretrained(args.model_dir, dtype=dtype)
    tokenizer = load_tokenizer(args.model_dir)

    text = Path(args.data).read_text()
    ids = tokenizer.encode(text, add_special_tokens=False).ids
    data = torch.tensor(ids, dtype=torch.long)
    total = 0.0
    with torch.no_grad():
        for _ in range(args.batches):
            starts = torch.randint(0, len(data) - args.context - 1, (args.batch_size,))
            x = torch.stack([data[s:s + args.context] for s in starts])
            y = torch.stack([data[s + 1:s + args.context + 1] for s in starts])
            _, loss = model(x, y)
            total += loss.item()
    loss = total / args.batches
    print(f"file: {args.data}  chars: {len(text)}  tokens: {len(data)}  "
          f"loss: {loss:.4f}  perplexity: {math.exp(loss):.1f}")
    print("Lower loss is better. Perplexity is exp(loss); it is not a quality judgement, only a fit measure.")


if __name__ == "__main__":
    main()
