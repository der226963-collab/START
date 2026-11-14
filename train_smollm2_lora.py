"""Narrow fine-tuning of SmolLM2-360M with hand-rolled LoRA.

Freezes the pretrained base weights (BF16) and trains only small
low-rank adapters on the attention projections, so the run fits on
CPU. The base weights are never modified and never leave the local
machine; only the adapter (a few MB) is saved, and it can be pushed
to GitHub on its own.

Data: a JSONL of {"instruction", "response", "source"} (built by
tools/build_finetune_data.py from data/instructions.txt and the
intent examples in mini_ai/data.py). Each example is formatted as
    ### Instruction:\n{instruction}\n### Response:\n{response}<eos>
and the loss is computed only on the response tokens (the prompt
is masked with -100), so the model learns to answer, not to
parrot the question.

Checkpointing: every --save-every steps (and at the end) the
adapter, optimizer state, step and epoch are written to --out, so
a run interrupted by a VM restart resumes with --resume and loses
only the steps since the last checkpoint.

Usage:
  python train_smollm2_lora.py --epochs 4 --out checkpoints/smollm2-lora-mix
  python train_smollm2_lora.py --out checkpoints/smollm2-lora-mix --resume
"""
import argparse
import json
import math
import random
import time
from pathlib import Path

import torch
import torch.nn.functional as F

from mini_ai.gpt.lora import (
    apply_lora,
    count_lora_parameters,
    load_lora_state_dict,
    lora_parameters,
    lora_state_dict,
)
from mini_ai.gpt.smollm2 import load_pretrained, load_tokenizer

ROOT = Path(__file__).resolve().parent
DEFAULT_MODEL_DIR = Path.home() / "workspace" / "models" / "smollm2-360m"


def load_jsonl(path):
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def encode_example(tokenizer, instruction, response, max_len, context=""):
    """Tokenize one example; return (input_ids, labels).

    Prompt tokens are masked (-100) in labels so loss is only on
    the response. The eos token ends the response. When context is
    given (RAG training), the prompt is
        ### Context:\n{context}\n\n### Instruction:\n{instruction}\n### Response:\n
    matching the retrieval eval harness, so the model learns to
    ground its answer on the retrieved fact. Without context the
    prompt is the plain instruction format.
    """
    if context:
        prompt = (f"### Context:\n{context}\n\n"
                  f"### Instruction:\n{instruction}\n### Response:\n")
    else:
        prompt = f"### Instruction:\n{instruction}\n### Response:\n"
    prompt_ids = tokenizer.encode(prompt, add_special_tokens=False).ids
    resp_ids = tokenizer.encode(response, add_special_tokens=False).ids
    eos = tokenizer.token_to_id("<|endoftext|>")
    input_ids = prompt_ids + resp_ids + [eos]
    labels = [-100] * len(prompt_ids) + resp_ids + [eos]
    if len(input_ids) > max_len:
        input_ids = input_ids[:max_len]
        labels = labels[:max_len]
    return input_ids, labels


def make_batches(examples, batch_size, rng):
    order = list(range(len(examples)))
    rng.shuffle(order)
    for i in range(0, len(order), batch_size):
        yield [examples[j] for j in order[i:i + batch_size]]


def pad_batch(batch, pad_id):
    """Right-pad a batch of (input_ids, labels) to the longest."""
    maxlen = max(len(ids) for ids, _ in batch)
    input_ids, labels, attn = [], [], []
    for ids, lab in batch:
        pad = maxlen - len(ids)
        input_ids.append(ids + [pad_id] * pad)
        labels.append(lab + [-100] * pad)
        attn.append([1] * len(ids) + [0] * pad)
    return (torch.tensor(input_ids, dtype=torch.long),
            torch.tensor(labels, dtype=torch.long),
            torch.tensor(attn, dtype=torch.long))


def save_checkpoint(out_dir, model, optimizer, step, epoch, args, train_loss):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    torch.save({
        "adapter": lora_state_dict(model),
        "optimizer": optimizer.state_dict(),
        "step": step,
        "epoch": epoch,
        "train_loss": train_loss,
        "args": vars(args),
    }, out_dir / "checkpoint.pt")
    meta = {
        "step": step, "epoch": epoch, "train_loss": train_loss,
        "lora_rank": args.rank, "lora_alpha": args.alpha,
        "lora_targets": args.target,
        "model": "HuggingFaceTB/SmolLM2-360M",
        "base_weights": "local only, not in this checkpoint",
    }
    (out_dir / "checkpoint.json").write_text(json.dumps(meta, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", default=str(DEFAULT_MODEL_DIR))
    ap.add_argument("--train-file", default="data/finetune/smollm2-mix-train.jsonl")
    ap.add_argument("--val-file", default="data/finetune/smollm2-mix-val.jsonl")
    ap.add_argument("--out", default="checkpoints/smollm2-lora-mix")
    ap.add_argument("--rank", type=int, default=8)
    ap.add_argument("--alpha", type=float, default=16.0)
    ap.add_argument("--target", default="q,k,v,o",
                    help="comma list of attention projections to adapt")
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--batch-size", type=int, default=2)
    ap.add_argument("--grad-accum", type=int, default=2)
    ap.add_argument("--max-len", type=int, default=256)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--save-every", type=int, default=25)
    ap.add_argument("--max-steps", type=int, default=0,
                    help="0 = no limit (smoke tests pass a small number)")
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    random.seed(args.seed)
    torch.set_num_threads(4)

    print(f"loading base model from {args.model_dir} ...", flush=True)
    model, config = load_pretrained(args.model_dir, dtype=torch.bfloat16)
    tokenizer = load_tokenizer(args.model_dir)
    pad_id = tokenizer.token_to_id("<|endoftext|>")

    suffixes = tuple(f"self_attn.{t}_proj" for t in args.target.split(","))
    apply_lora(model, target_suffixes=suffixes, r=args.rank, alpha=args.alpha)
    n_lora = count_lora_parameters(model)
    print(f"LoRA: rank {args.rank}, alpha {args.alpha}, targets {args.target}, "
          f"trainable params {n_lora} ({100 * n_lora / model.count_parameters():.3f}% of base)",
          flush=True)
    model.train()

    train_rows = load_jsonl(ROOT / args.train_file)
    val_rows = load_jsonl(ROOT / args.val_file)
    print(f"train examples: {len(train_rows)}, val examples: {len(val_rows)}", flush=True)
    train_ex = [encode_example(tokenizer, r["instruction"], r["response"],
                               args.max_len, r.get("context", ""))
                for r in train_rows]
    val_ex = [encode_example(tokenizer, r["instruction"], r["response"],
                             args.max_len, r.get("context", ""))
              for r in val_rows]

    optimizer = torch.optim.AdamW(lora_parameters(model), lr=args.lr,
                                  betas=(0.9, 0.95), weight_decay=0.0)
    # Constant LR with a short warmup is enough for a narrow run.
    def lr_at(step):
        warmup = 10
        return args.lr * min(1.0, (step + 1) / warmup)

    out_dir = Path(args.out)
    start_step, start_epoch = 0, 0
    if args.resume:
        ckpt = torch.load(out_dir / "checkpoint.pt", map_location="cpu", weights_only=False)
        load_lora_state_dict(model, ckpt["adapter"])
        optimizer.load_state_dict(ckpt["optimizer"])
        start_step, start_epoch = ckpt["step"], ckpt["epoch"]
        print(f"resumed from step {start_step}, epoch {start_epoch}", flush=True)

    step = start_step
    rng = random.Random(args.seed)
    t0 = time.time()
    done = False
    for epoch in range(start_epoch, args.epochs):
        if done:
            break
        batches = list(make_batches(train_ex, args.batch_size, rng))
        epoch_loss, epoch_n = 0.0, 0
        for bi, batch in enumerate(batches):
            if args.max_steps and step >= args.max_steps:
                done = True
                break
            for group in optimizer.param_groups:
                group["lr"] = lr_at(step)
            input_ids, labels, _ = pad_batch(batch, pad_id)
            logits, _ = model(input_ids)
            # Causal LM: logits at position i predict token i+1, so
            # shift before the loss. Without the shift the model is
            # trained to copy the token it already sees (an identity
            # task): the loss falls to ~0 and the val loss looks
            # perfect, but greedy generation still emits EOS at once.
            shift_logits = logits[:, :-1, :].contiguous()
            shift_labels = labels[:, 1:].contiguous()
            loss = F.cross_entropy(
                shift_logits.view(-1, shift_logits.size(-1)),
                shift_labels.view(-1), ignore_index=-100)
            (loss / args.grad_accum).backward()
            epoch_loss += loss.item()
            epoch_n += 1
            last_batch = bi == len(batches) - 1
            if epoch_n % args.grad_accum == 0 or last_batch:
                torch.nn.utils.clip_grad_norm_(lora_parameters(model), 1.0)
                optimizer.step()
                optimizer.zero_grad(set_to_none=True)
                step += 1
                if step % 5 == 0 or step == 1:
                    el = time.time() - t0
                    print(f"step {step} epoch {epoch} loss {loss.item():.4f} "
                          f"elapsed {el:.0f}s", flush=True)
                if step % args.save_every == 0:
                    save_checkpoint(out_dir, model, optimizer, step, epoch, args,
                                    epoch_loss / max(epoch_n, 1))
                    print(f"  checkpoint saved at step {step}", flush=True)
        print(f"epoch {epoch} done: mean loss {epoch_loss / max(epoch_n, 1):.4f}",
              flush=True)

    # Final validation loss (no gradients).
    model.eval()
    with torch.no_grad():
        val_loss, val_n = 0.0, 0
        for batch in make_batches(val_ex, args.batch_size, random.Random(args.seed)):
            input_ids, labels, _ = pad_batch(batch, pad_id)
            logits, _ = model(input_ids)
            shift_logits = logits[:, :-1, :].contiguous()
            shift_labels = labels[:, 1:].contiguous()
            val_loss += F.cross_entropy(
                shift_logits.view(-1, shift_logits.size(-1)),
                shift_labels.view(-1),
                ignore_index=-100).item()
            val_n += 1
    print(f"final val loss {val_loss / max(val_n, 1):.4f} "
          f"over {len(val_rows)} held-out examples", flush=True)
    save_checkpoint(out_dir, model, optimizer, step, args.epochs - 1, args,
                    epoch_loss / max(epoch_n, 1))
    print(f"done. adapter + checkpoint in {out_dir} "
          f"({time.time() - t0:.0f}s total)", flush=True)


if __name__ == "__main__":
    main()
