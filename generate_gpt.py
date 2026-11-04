"""Generate text from a MiniGPT checkpoint.

Usage:
  python generate_gpt.py --prompt "The garden " --length 200
  python generate_gpt.py --checkpoint checkpoints/mini-gpt --temperature 0.7

This is a language assistant, not a planner or a decider. Treat
its output as draft text to be checked by people, not as a plan
or an allocation.
"""
import argparse
import json
from pathlib import Path

import torch

from mini_ai.gpt import MiniGPT, GPTConfig, CharTokenizer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", default="checkpoints/mini-gpt")
    parser.add_argument("--prompt", default="The garden ")
    parser.add_argument("--length", type=int, default=200)
    parser.add_argument("--temperature", type=float, default=0.8)
    args = parser.parse_args()

    meta = json.loads(Path(args.checkpoint + ".json").read_text())
    if meta.get("tokenizer") == "bpe":
        from mini_ai.gpt.bpe import BPETokenizer
        tokenizer = BPETokenizer.from_json({"merges": meta["merges"], "vocab": meta["vocab"]})
        vocab_size = len(tokenizer)
    else:
        tokenizer = CharTokenizer.from_chars(meta["chars"])
        vocab_size = len(meta["chars"])
    if meta.get("architecture") == "modern":
        from mini_ai.gpt.model_modern import ModernConfig, ModernGPT
        cfg = ModernConfig(vocab_size=vocab_size, n_layer=meta["n_layer"],
                           n_head=meta["n_head"], n_embd=meta["n_embd"],
                           block_size=meta["block_size"])
        model = ModernGPT(cfg)
    else:
        cfg = GPTConfig(vocab_size=vocab_size, n_layer=meta["n_layer"],
                        n_head=meta["n_head"], n_embd=meta["n_embd"],
                        block_size=meta["block_size"])
        model = MiniGPT(cfg)
    model.load_state_dict(torch.load(args.checkpoint + ".pt", map_location="cpu"))

    unknown = sorted(set(args.prompt) - set(tokenizer.stoi))
    if unknown:
        print(f"Note: prompt characters not in the training vocab are skipped: {unknown}")
    idx = torch.tensor([tokenizer.encode(args.prompt)], dtype=torch.long)
    out = model.generate(idx, max_new_tokens=args.length, temperature=args.temperature)
    print(tokenizer.decode(out[0].tolist()))


if __name__ == "__main__":
    main()
