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
  - Resume: --resume <state-file> continues a run from the
    last saved state (model, optimizer, RNG, best checkpoint),
    and mixture runs cache their tokens next to --out, so a
    runtime restart costs at most 50 steps, not the run.
    The state is saved before the loop, at every eval point,
    and at the end.

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
from mini_ai.gpt.muon import Muon


def lr_at(step, total, base_lr, schedule):
    """Learning-rate schedule. Cosine is the old default.

    Trapezoid: linear warmup (first 5%), a long stable plateau,
    then linear decay to 10% of base over the last 20%. It is
    one of the CPU-portable pieces from the modded-nanogpt
    literature: it avoids the long high-LR tail of cosine
    while keeping most of training at full rate, and it needs
    no GPU-only code.
    """
    if schedule == "trapezoid":
        progress = step / max(1, total - 1)
        if progress < 0.05:
            return base_lr * (progress / 0.05)
        if progress < 0.80:
            return base_lr
        return base_lr * (1.0 - 0.9 * (progress - 0.80) / 0.20)
    progress = step / max(1, total - 1)
    return base_lr * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * progress)))

SIZES = {
    "tiny": dict(n_layer=2, n_head=4, n_embd=64, block_size=64),
    "small": dict(n_layer=4, n_head=4, n_embd=128, block_size=128),
    # Medium, added 2026-11-04 for the programming-language
    # wave (Python + Rust core, then C + Java): ~5M params
    # with a ~850-token vocab (untied; ~4.8M tied), still
    # CPU-trainable for short runs, but a 2,000-step run
    # will take several times the small model's ~78 minutes
    # — use it for smoke tests first, then a long run in
    # the background, not as a quick foreground job.
    "medium": dict(n_layer=6, n_head=8, n_embd=256, block_size=256),
    # Large, added 2026-11-05 after the six-language
    # batch: ~38M params tied with a ~850-token vocab
    # (12 layers, 512 width, 512 context). It fits in
    # the 8 GB VM only with a small batch (4, with
    # --grad-accum 2 for an effective batch of 8) and
    # is a multi-hour run on 4 CPU cores: roughly
    # 45-90 s/step, so 500 steps is 6-12 hours and
    # 2,000 steps is 1-2 days. Run medium first for
    # a baseline; large is defined and tested here
    # but has not had a training run yet.
    "large": dict(n_layer=12, n_head=8, n_embd=512, block_size=512),
}


def get_batch(data, block_size, batch_size):
    starts = torch.randint(0, len(data) - block_size - 1, (batch_size,))
    x = torch.stack([data[s:s + block_size] for s in starts])
    y = torch.stack([data[s + 1:s + block_size + 1] for s in starts])
    return x, y


class _MultiOptimizer:
    """Wrap two optimizers (Muon + AdamW) so training code can
    treat them as one: same param_groups, zero_grad and step."""

    def __init__(self, optimizers):
        self.optimizers = [opt for opt, _ in optimizers]

    @property
    def param_groups(self):
        groups = []
        for opt in self.optimizers:
            groups.extend(opt.param_groups)
        return groups

    def zero_grad(self):
        for opt in self.optimizers:
            opt.zero_grad()

    def step(self):
        for opt in self.optimizers:
            opt.step()

    def state_dict(self):
        # A list, one state_dict per wrapped optimizer, in
        # construction order. Rebuilt identically on resume,
        # so the order matches and load_state_dict lines up.
        return {"optimizers": [opt.state_dict() for opt in self.optimizers]}

    def load_state_dict(self, state):
        saved = state["optimizers"]
        if len(saved) != len(self.optimizers):
            raise ValueError(
                f"Optimizer state has {len(saved)} parts, "
                f"this wrapper has {len(self.optimizers)}")
        for opt, part in zip(self.optimizers, saved):
            opt.load_state_dict(part)


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


def sample_text(text, cap, blocks=100):
    """Representative sample of `text` capped at `cap` chars.

    Takes cap/blocks contiguous chars from the start of each
    of `blocks` evenly spaced blocks, so the sample covers
    the whole corpus (every book/language) while keeping real
    adjacent character pairs intact for BPE merge learning.
    Returns the text unchanged when it is already under the cap.
    """
    if len(text) <= cap:
        return text
    per_block = cap // blocks
    block_len = len(text) // blocks
    return "".join(text[i * block_len:i * block_len + per_block]
                   for i in range(blocks))


def encode_parts(tokenizer, parts):
    """Per-file 90/10 train/val split, as token id lists."""
    train, val = [], []
    for part_text in parts:
        tokens = tokenizer.encode(part_text)
        cut = int(0.9 * len(tokens))
        train.extend(tokens[:cut])
        val.extend(tokens[cut:])
    return train, val


def mix_tokens(textbook_train, textbook_val, code_train, code_val, ratio):
    """Mix textbook and code tokens at an explicit ratio.

    2026-11-04, separate code corpus: ratio is the fraction
    of the final train (and val) tokens that should be code.
    Textbook tokens are kept as-is; code tokens are repeated
    (whole copies, then trimmed) if there are fewer code
    tokens than the ratio needs, and trimmed if there are
    more. Repeating is explicit and reported, not hidden:
    a small code corpus at a high ratio will repeat, and
    that repetition is a real overfitting risk the caller
    should know about. Returns (train, val, code_used_train,
    code_used_val) as lists.
    """
    if ratio <= 0:
        return textbook_train, textbook_val, 0, 0
    if ratio >= 1:
        return code_train, code_val, len(code_train), len(code_val)
    if not code_train or not code_val:
        raise ValueError("Code corpus is empty, cannot mix at ratio > 0")

    def _mix(base, code):
        needed = int(len(base) * ratio / (1 - ratio))
        if needed <= 0:
            return base, 0
        repeats = (needed + len(code) - 1) // len(code)
        return base + (code * repeats)[:needed], needed

    train, used_train = _mix(textbook_train, code_train)
    val, used_val = _mix(textbook_val, code_val)
    return train, val, used_train, used_val


def run_state_path(out):
    """Path of the resumable run-state file for an --out base."""
    return Path(str(out) + "-state.pt")


def mixture_cache_base(out):
    """Base path of the run-scoped mixture token cache for an --out base.

    Three files live alongside <out>: <base>.pt (train/val token
    tensors), <base>.tokenizer.json (the BPE tokenizer) and
    <base>.meta.json (corpus hashes + config, for staleness checks).
    """
    return Path(str(out) + "-tokens")


def save_run_state(path, *, next_step, model, optimizer, best_val,
                   best_state, args, total_steps):
    """Save everything needed to continue a run from `next_step`.

    next_step is the number of steps already completed: the
    resumed run loops from step == next_step. The optimizer
    state covers both halves of a _MultiOptimizer (Muon
    momentum buffers + AdamW moments), and the RNG states
    make the resumed batch stream identical to an
    uninterrupted run's. Written atomically-ish: to a temp
    file first, then renamed, so a restart mid-write never
    leaves a half-written state file as the only copy.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "next_step": int(next_step),
        "total_steps": int(total_steps),
        "model_state": model.state_dict(),
        "optimizer_state": optimizer.state_dict(),
        "best_val": float(best_val),
        "best_state": best_state,
        "torch_rng_state": torch.get_rng_state(),
        "random_rng_state": random.getstate(),
        "args": dict(vars(args)),
    }
    tmp = path.with_suffix(".tmp.pt")
    torch.save(payload, str(tmp))
    tmp.replace(path)


def load_run_state(path):
    """Load a run-state file, or raise SystemExit with a clear reason."""
    path = Path(path)
    if not path.exists():
        raise SystemExit(f"--resume state file not found: {path}")
    try:
        state = torch.load(str(path), map_location="cpu", weights_only=True)
    except Exception as exc:  # corrupt or unreadable file
        raise SystemExit(f"--resume state file {path} could not be loaded: {exc}")
    required = ("next_step", "total_steps", "model_state", "optimizer_state",
                "best_val", "best_state", "torch_rng_state",
                "random_rng_state", "args")
    missing = [k for k in required if k not in state]
    if missing:
        raise SystemExit(
            f"--resume state file {path} is missing keys: {', '.join(missing)}")
    return state


def load_init_weights(path, *, size, modern, tokenizer,
                      dropout, qk_norm, tie_weights):
    """Load weights from a finished checkpoint to start a new leg.

    The checkpoint's architecture, size and tokenizer must match
    this run's, or it is a loud error — silently training a
    mismatched shape (or a different tokenizer's weights) would
    produce a model that looks trained and means nothing.
    Accepts the checkpoint base with or without the .pt suffix.
    Returns the state dict; the caller loads it into the model
    and starts a fresh optimizer and LR schedule for the leg.
    """
    base = str(path)
    if base.endswith(".pt"):
        base = base[:-3]
    meta_path = Path(base + ".json")
    pt_path = Path(base + ".pt")
    if not meta_path.exists():
        raise SystemExit(f"--init-from checkpoint metadata not found: {meta_path}")
    if not pt_path.exists():
        raise SystemExit(f"--init-from checkpoint weights not found: {pt_path}")
    try:
        meta = json.loads(meta_path.read_text())
    except Exception as exc:
        raise SystemExit(f"--init-from checkpoint metadata unreadable: {exc}")
    expected_arch = "modern" if modern else "classic"
    expected_size = SIZES[size]
    mismatches = []
    if meta.get("architecture") != expected_arch:
        mismatches.append(
            f"architecture: checkpoint {meta.get('architecture')!r} != run {expected_arch!r}")
    for key in ("n_layer", "n_head", "n_embd", "block_size"):
        if meta.get(key) != expected_size[key]:
            mismatches.append(
                f"{key}: checkpoint {meta.get(key)!r} != run {expected_size[key]!r}")
    if meta.get("dropout") != dropout:
        mismatches.append(
            f"dropout: checkpoint {meta.get('dropout')!r} != run {dropout!r}")
    if meta.get("qk_norm") != qk_norm:
        mismatches.append(
            f"qk_norm: checkpoint {meta.get('qk_norm')!r} != run {qk_norm!r}")
    if meta.get("tie_weights") != tie_weights:
        mismatches.append(
            f"tie_weights: checkpoint {meta.get('tie_weights')!r} != run {tie_weights!r}")
    if meta.get("tokenizer") == "bpe":
        if len(meta.get("vocab") or []) != len(tokenizer):
            mismatches.append(
                f"vocab size: checkpoint {len(meta.get('vocab') or [])} != run {len(tokenizer)}")
        elif meta.get("merges") != getattr(tokenizer, "merges", None):
            mismatches.append("BPE merges differ from the checkpoint's tokenizer")
    elif meta.get("tokenizer") == "char":
        if meta.get("chars") != getattr(tokenizer, "chars", None):
            mismatches.append("char tokenizer differs from the checkpoint's")
    else:
        mismatches.append(f"unknown checkpoint tokenizer: {meta.get('tokenizer')!r}")
    if mismatches:
        raise SystemExit(
            "--init-from checkpoint does not match this run:\n  "
            + "\n  ".join(mismatches))
    try:
        state = torch.load(str(pt_path), map_location="cpu", weights_only=True)
    except Exception as exc:
        raise SystemExit(f"--init-from checkpoint weights unreadable: {exc}")
    return state


def check_resume_args(saved_args, cli_args):
    """A resumed run must be the same run: every run-defining
    argument has to match what the state file recorded. The
    --resume path itself is exempt (it is the pointer, not
    the run). A mismatch is a loud error, never a silent
    retraining under the wrong config."""
    mismatches = []
    for key, saved_value in saved_args.items():
        if key == "resume":
            continue
        cli_value = getattr(cli_args, key, None)
        if cli_value != saved_value:
            mismatches.append(f"{key}: saved {saved_value!r} != CLI {cli_value!r}")
    if mismatches:
        raise SystemExit(
            "Cannot resume: run arguments differ from the saved run:\n  "
            + "\n  ".join(mismatches))


def save_mixture_cache(base, train_data, val_data, tokenizer, meta):
    """Save a run-scoped mixture token cache (BPE only).

    The flat --token-cache cannot represent a mixture ratio,
    so mixture runs get their own cache keyed by corpus
    hashes + ratio + BPE settings in `meta`. A later run
    with the same --out reuses it only if the hashes match.
    """
    base = Path(base)
    base.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"train": train_data, "val": val_data}, str(base.with_suffix(".pt")))
    base.with_suffix(".tokenizer.json").write_text(tokenizer.to_json())
    base.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2))
    print(f"Wrote mixture token cache: {len(train_data) + len(val_data):,} tokens to {base}.pt")


def load_mixture_cache(base, expected_meta):
    """Load a run-scoped mixture token cache, or return None.

    Returns (train_data, val_data, tokenizer) only when all
    three files exist, the stored meta's key fields match
    `expected_meta` exactly (corpus hashes, ratio, BPE
    settings), and the loaded tensors' lengths agree with
    the counts recorded when the cache was written. Anything
    else means "re-encode": a stale or corrupt cache is
    never silently reused. (Token counts cannot be part of
    the key: they are only known after encoding.)
    """
    base = Path(base)
    pt_path = base.with_suffix(".pt")
    tok_path = base.with_suffix(".tokenizer.json")
    meta_path = base.with_suffix(".meta.json")
    try:
        if not (pt_path.exists() and tok_path.exists() and meta_path.exists()):
            return None
        stored_meta = json.loads(meta_path.read_text())
        for key, value in expected_meta.items():
            if stored_meta.get(key) != value:
                return None
        payload = torch.load(str(pt_path), map_location="cpu", weights_only=True)
        train_data = payload["train"]
        val_data = payload["val"]
        if (len(train_data) != stored_meta.get("train_tokens")
                or len(val_data) != stored_meta.get("val_tokens")):
            return None
        tokenizer = BPETokenizer.from_json(json.loads(tok_path.read_text()))
        return train_data, val_data, tokenizer
    except Exception as exc:  # corrupt cache: re-encode, never crash the run
        print(f"Mixture token cache at {base}.pt unusable ({exc}); re-encoding.")
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--size", choices=SIZES, default="tiny")
    parser.add_argument("--steps", type=int, default=500)
    parser.add_argument("--batch", type=int, default=32)
    parser.add_argument("--lr", type=float, default=3e-3)
    parser.add_argument("--data", default="data/corpus.txt")
    parser.add_argument("--data-dir", default=None,
                        help="If set, train on all .txt files in this dir, sorted, instead of --data.")
    parser.add_argument("--code-dir", default=None,
                        help="Directory of code corpus .txt files (data/code/). "
                             "Used only with --code-ratio > 0.")
    parser.add_argument("--code-ratio", type=float, default=0.0,
                        help="Fraction of train/val tokens that should be code (0.0-1.0, default 0.0 = no code). "
                             "Code tokens are repeated if the code corpus is smaller than the ratio needs.")
    parser.add_argument("--dropout", type=float, default=0.0)
    parser.add_argument("--modern", action="store_true",
                        help="Use the modern transformer (RMSNorm, RoPE, SwiGLU) instead of the 2017-style model.")
    parser.add_argument("--tokenizer", choices=["char", "bpe"], default="char")
    parser.add_argument("--bpe-merges", type=int, default=300)
    parser.add_argument("--bpe-sample-chars", type=int, default=5_000_000,
                        help="Max chars of combined text used to TRAIN the BPE tokenizer "
                             "(default 5,000,000). The full corpus is still encoded with "
                             "the resulting tokenizer. Added 2026-11-05: training BPE on "
                             "the whole 69M-char corpus OOM-killed the run (exit 137) "
                             "while building the pair index over ~30M tokens, before any "
                             "training step. Merges learned on a representative sample "
                             "generalise; the sample is strided in contiguous blocks "
                             "across the whole text, not just the first N chars.")
    parser.add_argument("--optimizer", choices=["adamw", "muon"], default="adamw",
                        help="muon: Muon for hidden 2D weights, AdamW for the rest (modern model only).")
    parser.add_argument("--lr-schedule", choices=["cosine", "trapezoid"], default="cosine")
    parser.add_argument("--grad-accum", type=int, default=1,
                        help="Micro-batches per optimizer step; effective batch = --batch * --grad-accum.")
    parser.add_argument("--qk-norm", action="store_true",
                        help="Enable QK-normalisation in the modern model (off by default).")
    parser.add_argument("--tie-weights", action="store_true",
                        help="Tie the output head to the token embedding (saves params, helps small models).")
    parser.add_argument("--muon-lr", type=float, default=None,
                        help="Override Muon learning rate (published range 0.02-0.05; default uses --lr).")
    parser.add_argument("--token-cache", default=None,
                        help="Path to cache BPE tokens + tokenizer JSON (e.g. checkpoints/tokens.pt). "
                             "If it exists, tokenization is skipped; otherwise it is written after encoding.")
    parser.add_argument("--resume", default=None,
                        help="Path to a run-state file (<out>-state.pt) to continue from. "
                             "The saved run's arguments win: any CLI argument that differs "
                             "from the saved run is an error. The run continues from the "
                             "saved step with the LR schedule position preserved (the "
                             "schedule is a function of step/total, and the total is fixed).")
    parser.add_argument("--init-from", default=None,
                        help="Path to a checkpoint base (e.g. checkpoints/large-mix-500, "
                             "with or without the .pt suffix) whose weights start this "
                             "run. Starts a NEW leg: fresh optimizer, fresh LR schedule, "
                             "steps counted from 0. The checkpoint's architecture, size "
                             "and tokenizer must match this run's, or it is an error. "
                             "To resume a leg started with --init-from, pass the same "
                             "--init-from alongside --resume; a different one is an "
                             "error, and the state file's weights win on resume.")
    parser.add_argument("--out", default="checkpoints/mini-gpt")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    # --resume and --init-from are NOT mutually exclusive in
    # general: a leg started with --init-from must pass the
    # SAME --init-from again when it is resumed, because the
    # state file's saved arguments include it and
    # check_resume_args rejects a mismatch. What is forbidden
    # is a DIFFERENT init-from from the saved run's — and that
    # case is caught by check_resume_args below (saved value
    # vs CLI value), as is resuming a plain run with an
    # --init-from it never had. The resume path loads the
    # state file's weights, so on a resume the --init-from
    # value is only checked, never re-applied (see the
    # init-load site below).

    # Resume: the saved run's arguments are authoritative.
    # Load and check them before seeding or reading any data,
    # so a resumed run rebuilds the model and optimizer
    # identically to the run that wrote the state file.
    resume_state = None
    if args.resume:
        resume_state = load_run_state(args.resume)
        check_resume_args(resume_state["args"], args)
        merged = vars(args).copy()
        merged.update(resume_state["args"])
        merged["resume"] = args.resume
        args = argparse.Namespace(**merged)

    torch.manual_seed(args.seed)
    random.seed(args.seed)
    if args.data_dir:
        files = sorted(Path(args.data_dir).glob("*.txt"))
        # tools/assemble_code.py writes the assembled code
        # corpus to data/code_corpus.txt (top level of data/),
        # so a --data-dir data run would otherwise read the
        # whole code corpus as "textbook" text — and a mixture
        # run would then count the code twice (once here, once
        # via --code-dir). Caught 2026-11-05: the relaunched
        # 1,000-step mixture run reported 119,015,588 combined
        # chars instead of ~69M, i.e. ~80% code at a nominal
        # ratio of 0.3. The assembled code corpus is excluded
        # here; it is represented by --code-dir instead.
        files = [f for f in files if f.name != "code_corpus.txt"]
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
        parts = [text]
        provenance = [{"file": str(data_path), "chars": len(text),
                       "sha256": hashlib.sha256(text.encode()).hexdigest()}]
    if not (0.0 <= args.code_ratio <= 1.0):
        raise SystemExit("--code-ratio must be between 0.0 and 1.0")
    code_parts, code_provenance = [], []
    if args.code_ratio > 0:
        if not args.code_dir:
            raise SystemExit("--code-ratio > 0 requires --code-dir")
        code_files = sorted(Path(args.code_dir).glob("*.txt"))
        if not code_files:
            raise SystemExit(f"No .txt files in {args.code_dir}")
        for f in code_files:
            content = f.read_text()
            code_parts.append(f"\n--- {f.name} ---\n" + content)
            code_provenance.append({"file": str(f), "chars": len(content),
                                    "sha256": hashlib.sha256(content.encode()).hexdigest()})
    code_text = "".join(code_parts)
    # Token cache (BPE only): encoding 19M chars in Python is the
    # slowest part of a run, so a cache file lets repeat runs
    # skip both BPE training and encoding. The cache stores the
    # token ids plus the tokenizer JSON next to it, so a cached
    # run still knows exactly which tokenizer produced the ids.
    # Note: the cache is keyed only by path, not by corpus hash —
    # delete it after changing the corpus, or pass a new path.
    cache_path = Path(args.token_cache) if args.token_cache else None
    cache_tok_path = cache_path.with_suffix(".tokenizer.json") if cache_path else None
    if cache_path and code_parts:
        raise SystemExit("--token-cache cannot be used with --code-dir: "
                         "a flat token cache cannot represent a mixture ratio. "
                         "Drop --token-cache for mixture runs.")
    # Run-scoped mixture cache (BPE only): the flat cache
    # cannot represent a mixture, so mixture runs get their
    # own cache next to --out, keyed by corpus hashes +
    # ratio + BPE settings. A relaunch (including a resume
    # after a runtime restart) reuses it instead of
    # re-training BPE and re-encoding the ~69M-char corpus.
    # The flat cache can only hit when there are no code
    # parts, so the two caches never overlap.
    mixture_hit = None
    mixture_meta = None
    if code_parts and args.tokenizer == "bpe":
        mixture_meta = {
            "tokenizer": "bpe",
            "bpe_merges": args.bpe_merges,
            "bpe_sample_chars": args.bpe_sample_chars,
            "code_ratio": args.code_ratio,
            "data_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "code_sha256": hashlib.sha256(code_text.encode()).hexdigest(),
        }
        mixture_hit = load_mixture_cache(mixture_cache_base(args.out), mixture_meta)
    if cache_path and cache_path.exists() and cache_tok_path and cache_tok_path.exists():
        tokenizer = BPETokenizer.from_json(json.loads(cache_tok_path.read_text()))
        data = torch.load(str(cache_path), map_location="cpu", weights_only=True)
        # Per-file split is not recoverable from a flat cache, so
        # a cached run uses the same 90/10 split of the whole
        # token stream as the run that wrote the cache. The
        # per-file split below applies to uncached runs.
        split = int(0.9 * len(data))
        train_data, val_data = data[:split], data[split:]
        print(f"Loaded cached tokens: {len(data):,} tokens from {cache_path}")
    elif mixture_hit is not None:
        train_data, val_data, tokenizer = mixture_hit
        print(f"Loaded cached mixture tokens: {len(train_data) + len(val_data):,} tokens "
              f"from {mixture_cache_base(args.out)}.pt")
    else:
        # BPE is trained on textbook + code text together, so
        # code tokens (fn, let, ::, ->, etc.) are learned as
        # tokens instead of being split character by character.
        # The text is used once here, not at mixture ratio —
        # the ratio applies to training tokens below, not to
        # tokenizer training, so the tokenizer is not skewed
        # by repeating the code corpus.
        if args.tokenizer == "bpe":
            combined = text + code_text
            sample = sample_text(combined, args.bpe_sample_chars)
            tokenizer = BPETokenizer.train(sample, num_merges=args.bpe_merges)
            print(f"BPE tokenizer: {len(tokenizer)} tokens from {args.bpe_merges} merges "
                  f"(trained on {len(sample):,} of {len(combined):,} chars)")
        else:
            tokenizer = CharTokenizer(text + code_text)
        # Per-file 90/10 split (2026-11-04 fix): the old code
        # split the concatenated text at 90%, which made
        # validation a contiguous slice near the end of the
        # corpus (mostly the last book), not a representative
        # sample. Splitting each file separately keeps every
        # book represented in both train and validation.
        train_parts, val_parts = encode_parts(tokenizer, parts)
        if code_parts:
            code_train, code_val = encode_parts(tokenizer, code_parts)
            train_parts, val_parts, used_train, used_val = mix_tokens(
                train_parts, val_parts, code_train, code_val, args.code_ratio)
            print(f"Mixture: code_ratio {args.code_ratio}, code train tokens used "
                  f"{used_train:,} (unique {len(code_train):,}), "
                  f"code val tokens used {used_val:,} (unique {len(code_val):,})")
        train_data = torch.tensor(train_parts, dtype=torch.long)
        val_data = torch.tensor(val_parts, dtype=torch.long)
        if cache_path and args.tokenizer == "bpe":
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            torch.save(torch.tensor(train_parts + val_parts, dtype=torch.long), str(cache_path))
            cache_tok_path.write_text(tokenizer.to_json())
            print(f"Wrote token cache: {len(train_parts) + len(val_parts):,} tokens to {cache_path}")
        if code_parts and args.tokenizer == "bpe":
            # Token counts join the meta only at write time:
            # they are not known until after encoding.
            save_mixture_cache(
                mixture_cache_base(args.out), train_data, val_data, tokenizer,
                {**mixture_meta, "train_tokens": len(train_data),
                 "val_tokens": len(val_data)})
    # Clear error instead of a cryptic torch randint failure
    # when the context is longer than the data (hit 2026-11-04
    # testing medium, block_size 256, on the 3,302-char corpus:
    # val was ~200 tokens, so get_batch crashed). Medium needs
    # a large corpus, not a small smoke file.
    _bs = SIZES[args.size]["block_size"]
    if len(train_data) <= _bs or len(val_data) <= _bs:
        raise SystemExit(
            f"Data too small for block_size {_bs}: train {len(train_data)} tokens, "
            f"val {len(val_data)} tokens. Use a larger corpus (e.g. --data-dir data) "
            f"or a smaller --size.")
    if args.modern:
        cfg = ModernConfig(vocab_size=len(tokenizer), dropout=args.dropout,
                           qk_norm=args.qk_norm, tie_weights=args.tie_weights, **SIZES[args.size])
        model = ModernGPT(cfg)
    else:
        cfg = GPTConfig(vocab_size=len(tokenizer), dropout=args.dropout,
                        tie_weights=args.tie_weights, **SIZES[args.size])
        model = MiniGPT(cfg)
    print(f"Parameters: {model.count_parameters():,}  vocab: {len(tokenizer)}  "
          f"layers: {cfg.n_layer}  embd: {cfg.n_embd}  context: {cfg.block_size}")
    print(f"Train tokens: {len(train_data):,}  val tokens: {len(val_data):,}")

    if args.init_from and resume_state is None:
        # Warm start for a new leg: the weights come from a
        # finished checkpoint, but the optimizer, the LR
        # schedule and the step count all start fresh below.
        # Skipped on a resume: the state file's weights win
        # there (loaded in the resume block below), and the
        # --init-from value was already checked against the
        # saved run's by check_resume_args.
        init_state = load_init_weights(
            args.init_from, size=args.size, modern=args.modern,
            tokenizer=tokenizer, dropout=args.dropout,
            qk_norm=args.qk_norm, tie_weights=args.tie_weights)
        model.load_state_dict(init_state)
        print(f"Initialized from {args.init_from}: weights loaded, "
              f"fresh optimizer and LR schedule for this leg.")

    if args.optimizer == "muon" and args.modern:
        # Muon for hidden 2D matrices, AdamW for embeddings,
        # the output head, biases and norms.
        muon_params, adam_params = [], []
        for name, p in model.named_parameters():
            if p.ndim == 2 and "token_emb" not in name and "head" not in name:
                muon_params.append(p)
            else:
                adam_params.append(p)
        optimizer = _MultiOptimizer([
            # --muon-lr overrides --lr for Muon only (2026-11-04
            # tuning note: published Muon range is 0.02-0.05, but
            # it is NOT raised blindly here — default still uses
            # --lr, and a higher value must be chosen explicitly).
            (Muon(muon_params, lr=args.muon_lr if args.muon_lr is not None else args.lr, weight_decay=0.01), "muon"),
            (torch.optim.AdamW(adam_params, lr=args.lr, weight_decay=0.01), "adamw"),
        ])
    else:
        if args.optimizer == "muon" and not args.modern:
            print("Note: --optimizer muon needs --modern; falling back to AdamW.")
        optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.01)
    best_val = float("inf")
    best_state = None
    final_train_loss = None
    total_steps = args.steps
    start_step = 0
    # The state file for this run: the --resume path when
    # resuming (so later saves keep landing in the same
    # file), otherwise <out>-state.pt.
    state_path = Path(args.resume) if args.resume else run_state_path(args.out)
    if resume_state is not None:
        start_step = resume_state["next_step"]
        model.load_state_dict(resume_state["model_state"])
        optimizer.load_state_dict(resume_state["optimizer_state"])
        torch.set_rng_state(resume_state["torch_rng_state"])
        random.setstate(resume_state["random_rng_state"])
        best_val = resume_state["best_val"]
        best_state = resume_state["best_state"]
        print(f"Resumed from {args.resume}: continuing at step "
              f"{start_step}/{total_steps}, best val {best_val:.4f}")
    # First state save, before the loop: a restart in the
    # first minutes must already have something to resume
    # from. (Tokenization precedes this and is covered by
    # the token cache instead — the model cannot exist
    # before its tokenizer does.)
    save_run_state(state_path, next_step=start_step, model=model,
                   optimizer=optimizer, best_val=best_val,
                   best_state=best_state, args=args, total_steps=total_steps)
    accum = max(1, args.grad_accum)
    for step in range(start_step, total_steps):
        lr = lr_at(step, total_steps, args.lr, args.lr_schedule)
        for group in optimizer.param_groups:
            group["lr"] = lr
        # Gradient accumulation: average the loss over micro-batches.
        micro_loss = 0.0
        optimizer.zero_grad()
        for _ in range(accum):
            x, y = get_batch(train_data, cfg.block_size, args.batch)
            _, loss = model(x, y)
            (loss / accum).backward()
            micro_loss += loss.item() / accum
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        final_train_loss = micro_loss
        if step % 50 == 0 or step == total_steps - 1:
            val_loss = evaluate(model, val_data, cfg.block_size)
            if val_loss < best_val:
                best_val = val_loss
                best_state = copy.deepcopy(model.state_dict())
                # Save the best checkpoint immediately, not only at the end:
                # a runtime restart used to lose a whole long run with
                # nothing saved. This keeps the best-so-far on disk.
                _out = Path(args.out)
                _out.parent.mkdir(parents=True, exist_ok=True)
                torch.save(best_state, _out.with_suffix(".pt"))
                print(f"  (saved best checkpoint so far, val {best_val:.4f})")
            print(f"step {step:5d}  train {micro_loss:.4f}  val {val_loss:.4f}  lr {lr:.2e}")
            # Run state at every eval point, so a restart
            # loses at most the 50 steps since the last one.
            save_run_state(state_path, next_step=step + 1, model=model,
                           optimizer=optimizer, best_val=best_val,
                           best_state=best_state, args=args,
                           total_steps=total_steps)
        # Mid-eval state save: two runtime restarts have already
        # hit this run, and the 50-step cadence loses ~30 min of
        # training each time. Saving halfway between evals too
        # caps the loss at 25 steps (~15 min). The write is
        # atomic (temp file + rename), so a restart mid-write
        # cannot corrupt the state.
        if (step + 1) % 25 == 0:
            save_run_state(state_path, next_step=step + 1, model=model,
                           optimizer=optimizer, best_val=best_val,
                           best_state=best_state, args=args,
                           total_steps=total_steps)
            print(f"  (saved run state, step {step + 1})")
    # Final state save, so a run that reached its total can
    # still be resumed (idempotently) and its state inspected.
    save_run_state(state_path, next_step=total_steps, model=model,
                   optimizer=optimizer, best_val=best_val,
                   best_state=best_state, args=args, total_steps=total_steps)

    if best_state is not None:
        model.load_state_dict(best_state)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), out.with_suffix(".pt"))
    (out.with_suffix(".json")).write_text(json.dumps({
        "tokenizer": args.tokenizer,
        # getattr defaults are evaluated eagerly in Python, so the
        # old code crashed on char tokenizers (no .vocab) even
        # though .chars existed. Use None as the safe default.
        "chars": getattr(tokenizer, "chars", None),
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
        "resumed_from": args.resume,
        "optimizer": args.optimizer, "lr_schedule": args.lr_schedule,
        "grad_accum": accum, "qk_norm": args.qk_norm,
        "tie_weights": args.tie_weights, "muon_lr": args.muon_lr,
        "code_ratio": args.code_ratio, "code_files": code_provenance,
        "final_train_loss": final_train_loss, "best_val_loss": best_val,
        "init_from": args.init_from,
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
