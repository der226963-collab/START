"""Generate text from a MiniGPT checkpoint.

Usage:
  python generate_gpt.py --prompt "The garden " --length 200
  python generate_gpt.py --checkpoint checkpoints/mini-gpt --temperature 0.7
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
    cfg = GPTConfig(vocab_size=len(meta["chars"]), n_layer=meta["n_layer"],
                    n_head=meta["n_head"], n_embd=meta["n_embd"],
                    block_size=meta["block_size"])
    model = MiniGPT(cfg)
    model.load_state_dict(torch.load(args.checkpoint + ".pt", map_location="cpu"))
    tokenizer = CharTokenizer("".join(meta["chars"]))
    # CharTokenizer sorts its chars, so rebuild the exact mapping from meta.
    tokenizer.chars = meta["chars"]
    tokenizer.stoi = {ch: i for i, ch in enumerate(meta["chars"])}
    tokenizer.itos = {i: ch for ch, i in tokenizer.stoi.items()}

    idx = torch.tensor([tokenizer.encode(args.prompt)], dtype=torch.long)
    out = model.generate(idx, max_new_tokens=args.length, temperature=args.temperature)
    print(tokenizer.decode(out[0].tolist()))


if __name__ == "__main__":
    main()
