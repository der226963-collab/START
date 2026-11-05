"""Evaluate a saved MiniGPT checkpoint on a text file.

Reports validation-style loss and perplexity (exp(loss)) on the
given file, using the checkpoint's saved vocabulary. This is how
a model is compared honestly: same file, same metric, no training
on the evaluation text in this script.

Usage:
  python evaluate_gpt.py --checkpoint checkpoints/mini-gpt --data data/weather.txt
  python evaluate_gpt.py --checkpoint checkpoints/mini-gpt --data data/corpus.txt
"""
import argparse
import json
import math
from pathlib import Path

import torch

from mini_ai.gpt import MiniGPT, GPTConfig, CharTokenizer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", default="checkpoints/mini-gpt")
    parser.add_argument("--data", required=True)
    parser.add_argument("--batches", type=int, default=20)
    parser.add_argument("--modern", action="store_true")
    parser.add_argument("--seed", type=int, default=42,
                        help="Seed for evaluation batches, so two runs on the same checkpoint are comparable (2026-11-04 fix).")
    args = parser.parse_args()
    torch.manual_seed(args.seed)

    meta = json.loads(Path(args.checkpoint + ".json").read_text())
    if meta.get("tokenizer") == "bpe":
        from mini_ai.gpt.bpe import BPETokenizer
        tokenizer = BPETokenizer.from_json({"merges": meta["merges"], "vocab": meta["vocab"]})
    else:
        tokenizer = CharTokenizer.from_chars(meta["chars"])
    if args.modern or meta.get("architecture") == "modern":
        from mini_ai.gpt.model_modern import ModernGPT, ModernConfig
        cfg = ModernConfig(vocab_size=len(tokenizer), n_layer=meta["n_layer"],
                           n_head=meta["n_head"], n_embd=meta["n_embd"],
                           block_size=meta["block_size"], dropout=0.0,
                           qk_norm=meta.get("qk_norm", False),
                           tie_weights=meta.get("tie_weights", False))
        model = ModernGPT(cfg)
    else:
        cfg = GPTConfig(vocab_size=len(tokenizer), n_layer=meta["n_layer"],
                        n_head=meta["n_head"], n_embd=meta["n_embd"],
                        block_size=meta["block_size"], dropout=0.0,
                        tie_weights=meta.get("tie_weights", False))
        model = MiniGPT(cfg)
    model.load_state_dict(torch.load(args.checkpoint + ".pt", map_location="cpu"))
    model.eval()

    text = Path(args.data).read_text()
    data = torch.tensor(tokenizer.encode(text), dtype=torch.long)
    total = 0.0
    with torch.no_grad():
        for _ in range(args.batches):
            starts = torch.randint(0, len(data) - cfg.block_size - 1, (32,))
            x = torch.stack([data[s:s + cfg.block_size] for s in starts])
            y = torch.stack([data[s + 1:s + cfg.block_size + 1] for s in starts])
            _, loss = model(x, y)
            total += loss.item()
    loss = total / args.batches
    print(f"file: {args.data}  chars: {len(text)}  loss: {loss:.4f}  perplexity: {math.exp(loss):.1f}")
    print("Lower loss is better. Perplexity is exp(loss); it is not a quality judgement, only a fit measure.")


if __name__ == "__main__":
    main()
