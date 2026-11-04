"""Train MiniGPT on a small text corpus, then show a sample generation.

What changed in this version, and why:
  - Train / validation split: before, the model was scored only on
    text it had already trained on, so a falling loss could mean
    memorisation, not learning. Now 10% of the text is held out
    and reported separately.
  - Cosine learning-rate decay + gradient clipping: standard
    small-model practice, and it makes longer runs more stable.
  - Best checkpoint: the saved model is the one with the lowest
    validation loss, not just the last step.
  - Provenance in the checkpoint JSON: data file, its SHA-256,
    sizes, seed, and config, so a later reader can tell exactly
    what this model was trained on. That is a PCAC habit: data
    source and limits travel with the model, not in a separate
    story about it.

Usage:
  python train_gpt.py                      # tiny model, quick CPU run
  python train_gpt.py --size small         # 128-dim, 4 layers, ~800k params
  python train_gpt.py --size small --steps 2000 --data data/corpus.txt
  python train_gpt.py --data-dir data      # train on all .txt files in data/
  python train_gpt.py --dropout 0.1        # regularisation for larger runs

PCAC note: this model predicts text. It does not allocate
resources and it does not decide. Allocation is a separate
planning layer under hard limits; decisions are for a human
assembly. See README.md, "How this fits PCAC".
"""
import argparse
import copy
import hashlib
import json
import math
import random
from pathlib import Path

import torch

from mini_ai.gpt import MiniGPT, GPTConfig, CharTokenizer
from mini_ai.gpt.bpe import BPETokenizer
from mini_ai.gpt.model_modern import ModernGPT, ModernConfig

SIZES = {
    "tiny": dict(n_layer=2, n_head=4, n_embd=64, block_size=64),
    "small": dict(n_layer=4, n_head=4, n_embd=128, block_size=128),
}


def get_batch(data, block_size, batch_size):
    starts = torch.randint(0, len(data) - block_size - 1, (batch_size,))
    x = torch.stack([data[s:s + block_size] for s in starts])
    y = torch.stack([data[s + 1:s + block_size + 1] for s in starts])
    return x, y


@torch.no_grad()
def evaluate(model, data, block_size, batches=20, batch_size=32):
    model.eval()
    total = 0.0
    for _ in range(batches):
        x, y = get_batch(data, block_size, batch_size)
        _, loss = model(x, y)
        total += loss.item()
    model.train()
    return total / batches


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--size", choices=SIZES, default="tiny")
    parser.add_argument("--steps", type=int, default=500)
    parser.add_argument("--batch", type=int, default=32)
    parser.add_argument("--lr", type=float, default=3e-3)
    parser.add_argument("--data", default="data/corpus.txt")
    parser.add_argument("--data-dir", default=None,
                        help="If set, train on all .txt files in this dir, sorted, instead of --data.")
    parser.add_argument("--dropout", type=float, default=0.0)
    parser.add_argument("--modern", action="store_true",
                        help="Use the modern transformer (RMSNorm, RoPE, SwiGLU) instead of the 2017-style model.")
    parser.add_argument("--tokenizer", choices=["char", "bpe"], default="char")
    parser.add_argument("--bpe-merges", type=int, default=300)
    parser.add_argument("--out", default="checkpoints/mini-gpt")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    torch.manual_seed(args.seed)
    random.seed(args.seed)
    if args.data_dir:
        files = sorted(Path(args.data_dir).glob("*.txt"))
        if not files:
            raise SystemExit(f"No .txt files in {args.data_dir}")
        parts = []
        provenance = []
        for f in files:
            content = f.read_text()
            parts.append(f"\n--- {f.name} ---\n" + content)
            provenance.append({"file": str(f), "chars": len(content),
                               "sha256": hashlib.sha256(content.encode()).hexdigest()})
        text = "".join(parts)
        data_path = Path(args.data_dir)
    else:
        data_path = Path(args.data)
        text = data_path.read_text()
        provenance = [{"file": str(data_path), "chars": len(text),
                       "sha256": hashlib.sha256(text.encode()).hexdigest()}]
    if args.tokenizer == "bpe":
        tokenizer = BPETokenizer.train(text, num_merges=args.bpe_merges)
        print(f"BPE tokenizer: {len(tokenizer)} tokens from {args.bpe_merges} merges")
    else:
        tokenizer = CharTokenizer(text)
    data = torch.tensor(tokenizer.encode(text), dtype=torch.long)
    split = int(0.9 * len(data))
    train_data, val_data = data[:split], data[split:]
    if args.modern:
        cfg = ModernConfig(vocab_size=len(tokenizer), dropout=args.dropout, **SIZES[args.size])
        model = ModernGPT(cfg)
    else:
        cfg = GPTConfig(vocab_size=len(tokenizer), dropout=args.dropout, **SIZES[args.size])
        model = MiniGPT(cfg)
    print(f"Parameters: {model.count_parameters():,}  vocab: {len(tokenizer)}  "
          f"layers: {cfg.n_layer}  embd: {cfg.n_embd}  context: {cfg.block_size}")
    print(f"Train tokens: {len(train_data):,}  val tokens: {len(val_data):,}")

    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.01)
    best_val = float("inf")
    best_state = None
    final_train_loss = None
    for step in range(args.steps):
        # Cosine decay to 10% of the starting rate.
        progress = step / max(1, args.steps - 1)
        lr = args.lr * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * progress)))
        for group in optimizer.param_groups:
            group["lr"] = lr
        x, y = get_batch(train_data, cfg.block_size, args.batch)
        _, loss = model(x, y)
        optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        final_train_loss = loss.item()
        if step % 50 == 0 or step == args.steps - 1:
            val_loss = evaluate(model, val_data, cfg.block_size)
            if val_loss < best_val:
                best_val = val_loss
                best_state = copy.deepcopy(model.state_dict())
            print(f"step {step:5d}  train {loss.item():.4f}  val {val_loss:.4f}  lr {lr:.2e}")

    if best_state is not None:
        model.load_state_dict(best_state)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), out.with_suffix(".pt"))
    (out.with_suffix(".json")).write_text(json.dumps({
        "tokenizer": args.tokenizer,
        "chars": getattr(tokenizer, "chars", tokenizer.vocab),
        "vocab": getattr(tokenizer, "vocab", None),
        "merges": getattr(tokenizer, "merges", None),
        "n_layer": cfg.n_layer, "n_head": cfg.n_head,
        "n_embd": cfg.n_embd, "block_size": cfg.block_size,
        "architecture": "modern" if args.modern else "classic",
        "dropout": cfg.dropout,
        "data_file": str(data_path),
        "data_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "data_files": provenance,
        "train_tokens": len(train_data), "val_tokens": len(val_data),
        "seed": args.seed, "steps": args.steps,
        "final_train_loss": final_train_loss, "best_val_loss": best_val,
        "intended_use": "Language assistance only. Not a planner, allocator, or decider. "
                       "Human assemblies decide; a separate planning layer checks allocations.",
    }, indent=2))
    print(f"Saved best checkpoint (val {best_val:.4f}) to {out}.pt (+ .json)")

    prompt = "The garden "
    idx = torch.tensor([tokenizer.encode(prompt)], dtype=torch.long)
    generated = model.generate(idx, max_new_tokens=120, temperature=0.8)
    print("\nSample generation:")
    print(tokenizer.decode(generated[0].tolist()))


if __name__ == "__main__":
    main()
