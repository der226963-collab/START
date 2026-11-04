"""Train MiniGPT on a small text corpus, then show a sample generation.

Usage:
  python train_gpt.py                      # tiny model, quick CPU run
  python train_gpt.py --size small         # 128-dim, 4 layers, ~800k params
  python train_gpt.py --size small --steps 2000 --data data/corpus.txt

Checkpoints are saved as JSON (vocab + config) + a .pt state dict,
so generate_gpt.py can load them without the training script.
"""
import argparse
import json
import random
from pathlib import Path

import torch

from mini_ai.gpt import MiniGPT, GPTConfig, CharTokenizer

SIZES = {
    "tiny": dict(n_layer=2, n_head=4, n_embd=64, block_size=64),
    "small": dict(n_layer=4, n_head=4, n_embd=128, block_size=128),
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--size", choices=SIZES, default="tiny")
    parser.add_argument("--steps", type=int, default=300)
    parser.add_argument("--batch", type=int, default=32)
    parser.add_argument("--lr", type=float, default=3e-3)
    parser.add_argument("--data", default="data/corpus.txt")
    parser.add_argument("--out", default="checkpoints/mini-gpt")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    torch.manual_seed(args.seed)
    random.seed(args.seed)
    text = Path(args.data).read_text()
    tokenizer = CharTokenizer(text)
    data = torch.tensor(tokenizer.encode(text), dtype=torch.long)
    cfg = GPTConfig(vocab_size=len(tokenizer), **SIZES[args.size])
    model = MiniGPT(cfg)
    print(f"Parameters: {model.count_parameters():,}  vocab: {len(tokenizer)}  "
          f"layers: {cfg.n_layer}  embd: {cfg.n_embd}  context: {cfg.block_size}")

    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr)
    for step in range(args.steps):
        starts = torch.randint(0, len(data) - cfg.block_size - 1, (args.batch,))
        x = torch.stack([data[s:s + cfg.block_size] for s in starts])
        y = torch.stack([data[s + 1:s + cfg.block_size + 1] for s in starts])
        _, loss = model(x, y)
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        if step % 50 == 0 or step == args.steps - 1:
            print(f"step {step:5d}  loss {loss.item():.4f}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), out.with_suffix(".pt"))
    (out.with_suffix(".json")).write_text(json.dumps({
        "chars": tokenizer.chars,
        "n_layer": cfg.n_layer, "n_head": cfg.n_head,
        "n_embd": cfg.n_embd, "block_size": cfg.block_size,
    }))
    print(f"Saved checkpoint to {out}.pt (+ .json)")

    prompt = "The garden "
    idx = torch.tensor([tokenizer.encode(prompt)], dtype=torch.long)
    generated = model.generate(idx, max_new_tokens=120, temperature=0.8)
    print("\nSample generation:")
    print(tokenizer.decode(generated[0].tolist()))


if __name__ == "__main__":
    main()
