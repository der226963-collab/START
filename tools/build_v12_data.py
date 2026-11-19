"""Build the SmolLM2 LoRA v12 training dataset (v9 + plain-narrative replay).

v12 = v9's train set verbatim (169 rows from
data/finetune/smollm2-rag-v9-train.jsonl: 100 instruction rows with
context + 69 intent rows, including the 6 thanks paraphrases)
+ 19 "continue this passage" replay rows sampled from Darwin's
Origin of Species, First Edition 1859 (data/expanded/pg1228.txt,
public domain, recorded in data/expanded/SOURCES.md), so replay is
~10% of the training rows. Total 188 rows.

This is the single-factor change vs v9 (data mixture only) and a
genuinely different replay hypothesis from v10's: v10's 54 replay
rows were mostly fragmented Webster's dictionary definitions
(data/expanded/pg660.txt) at 24% — the wrong genre as well as the
wrong fraction. v12's replay is continuous narrative prose at ~10%.

Everything else is v9's exact recipe: rank 16, alpha 32, q/k/v/o,
LR 2e-4, AdamW, constant LR, 12 epochs, batch 2, grad-accum 2,
seed 42, --save-every 25, from the BASE model. LR stays 2e-4: this
leg does NOT combine with v11's gentler LR (that would repeat v8's
confound mistake).

Replay framing (same as v8/v10, plain continuation in the trainer's
existing row format -- no "context" key):
  instruction = "Continue the following passage.\\n\\n" + first half of
                a short Origin chunk
  response    = second half of the same chunk
  source      = "replay-corpus"

Sampling: fixed seed 42 (the project's standard seed). Candidate
chunks are built by joining consecutive non-empty lines of the Origin
body (lines 285-14589 of pg1228.txt: from "INTRODUCTION." to just
before "INDEX.") until ~420 characters (kept to 300-500 chars total
per row, well inside the trainer's --max-len 256 tokens). All-caps
chapter heading lines are skipped while building a chunk, so a chunk
is pure narrative prose. Chunks are rejected for quality
(Gutenberg boilerplate, too few words, too many digits, no sentence
boundary to split on) or by screening (below).

Screening (same two standards as tools/build_v10_data.py):
(a) ALL rows: no train instruction may equal (normalized) any probe
    instruction or any val instruction; no probe question may appear
    as a phrase in any row (instruction, response or context); no
    heldout_text.txt line/sentence (>= 30 chars) may appear in any
    row.
(b) REPLAY rows only: the full v8 screening as well -- val questions
    as phrases, and >=70% of a probe/val question's content words.
    The v9 rows are NOT put through (b): the val instructions
    "goodbye" and "hi" are the intent vocabulary itself, so they
    legitimately appear in intent responses ("Goodbye for now..."),
    and the RAG facts are *supposed* to overlap the probe questions
    topically.

Usage:
  python tools/build_v12_data.py [--seed 42]
Output:
  data/finetune/smollm2-rag-v12-train.jsonl
  data/finetune/smollm2-rag-v12-train.jsonl.json  (provenance)
"""
import argparse
import hashlib
import json
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

V9_TRAIN = ROOT / "data" / "finetune" / "smollm2-rag-v9-train.jsonl"
VAL = ROOT / "data" / "finetune" / "smollm2-rag-v9-val.jsonl"
ORIGIN = ROOT / "data" / "expanded" / "pg1228.txt"
SOURCES = ROOT / "data" / "expanded" / "SOURCES.md"
PROBE = ROOT / "eval" / "finetune-probe-v5.jsonl"
HELDOUT = ROOT / "eval" / "heldout_text.txt"
OUT = ROOT / "data" / "finetune" / "smollm2-rag-v12-train.jsonl"

SEED = 42
N_REPLAY = 19
CHUNK_MIN = 300
CHUNK_TARGET = 420
CHUNK_MAX = 500
# Body of the Origin in pg1228.txt: line 285 is "INTRODUCTION.",
# line 14590 is "INDEX." (1-based). Everything before is Gutenberg
# header + contents; everything from the index on is the index.
BODY_START = 285
BODY_END = 14590


def load_jsonl(path):
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def key(row):
    return json.dumps(row, sort_keys=True)


def norm(text):
    return re.sub(r"\s+", " ", text.strip().lower())


def content_words(text):
    return {w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 3}


def split_chunk(chunk):
    """Split near the midpoint at a sentence boundary if possible."""
    mid = len(chunk) // 2
    # Search for ". " boundaries in the middle third of the chunk.
    lo, hi = len(chunk) // 3, 2 * len(chunk) // 3
    best = None
    for m in re.finditer(r"\.\s", chunk):
        if lo <= m.start() <= hi:
            if best is None or abs(m.start() - mid) < abs(best - mid):
                best = m.start()
    if best is not None:
        return chunk[: best + 1].strip(), chunk[best + 1:].strip()
    # Fallback: nearest space to the midpoint.
    for i in range(mid, len(chunk)):
        if chunk[i] == " ":
            return chunk[:i].strip(), chunk[i + 1:].strip()
    return None, None


def build_chunk(lines, start, stats):
    """Join consecutive non-empty lines from `start` into one chunk.

    All-caps heading lines (e.g. 'CHAPTER I.', chapter titles) are
    skipped, so a chunk is pure narrative prose.
    """
    parts, chars = [], 0
    i = start
    while i < len(lines) and chars < CHUNK_TARGET and len(parts) < 40:
        line = lines[i].strip()
        i += 1
        if not line:
            continue
        if is_heading_line(line):
            stats["heading_lines_skipped"] += 1
            continue
        parts.append(line)
        chars += len(line) + 1
    if not parts:
        return None
    text = re.sub(r"\s+", " ", " ".join(parts)).strip()
    if len(text) > CHUNK_MAX:
        cut = text.rfind(" ", 0, CHUNK_MAX)
        text = text[:cut].strip() if cut > CHUNK_MIN else None
    return text


def is_heading_line(line):
    """An all-caps heading line, e.g. 'CHAPTER I.' or a chapter title."""
    s = line.strip()
    return len(s) > 12 and s == s.upper() and any(c.isalpha() for c in s) \
        and not any(c.islower() for c in s)


def quality_ok(text):
    if text is None or not (CHUNK_MIN <= len(text) <= CHUNK_MAX):
        return False
    if "gutenberg" in text.lower() or "project gutenberg" in text.lower():
        return False
    words = text.split()
    if len(words) < 45:
        return False
    if text.count(".") < 1:
        return False
    digits = sum(c.isdigit() for c in text)
    if digits / len(text) > 0.15:
        return False
    if "http" in text.lower():
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args()

    v9_rows = load_jsonl(V9_TRAIN)
    assert len(v9_rows) == 169, f"expected 169 v9 rows, got {len(v9_rows)}"
    with_context = [r for r in v9_rows if r.get("context")]
    intents = [r for r in v9_rows if r.get("source", "").startswith("intent:")]
    assert len(with_context) == 100, \
        f"expected 100 v9 rows with context, got {len(with_context)}"
    assert len(intents) == 69, \
        f"expected 69 v9 intent rows, got {len(intents)}"
    val_before = hashlib.sha256(VAL.read_bytes()).hexdigest()
    assert val_before.startswith("2743e47d"), \
        f"val sha256 mismatch: {val_before[:8]}"
    val_rows = load_jsonl(VAL)
    assert len(val_rows) == 8, f"expected 8 val rows, got {len(val_rows)}"
    probe_rows = load_jsonl(PROBE)
    assert len(probe_rows) == 8, f"expected 8 probe rows, got {len(probe_rows)}"

    origin_bytes = ORIGIN.read_bytes()
    origin_sha = hashlib.sha256(origin_bytes).hexdigest()
    origin_lines = origin_bytes.decode(errors="replace").splitlines()
    body = origin_lines[BODY_START - 1:BODY_END - 1]
    assert body[0].strip() == "INTRODUCTION.", \
        f"body start mismatch: {body[0].strip()!r}"
    assert origin_lines[BODY_END - 1].strip() == "INDEX.", \
        f"body end mismatch: {origin_lines[BODY_END - 1].strip()!r}"

    # --- Screening material (same as build_v10_data.py) --------------------
    forbidden_questions = [norm(r["instruction"]) for r in probe_rows]
    forbidden_q_words = [content_words(r["instruction"])
                         for r in probe_rows + val_rows]
    val_instructions = [norm(r["instruction"]) for r in val_rows]
    probe_instructions = [norm(r["instruction"]) for r in probe_rows]
    heldout = HELDOUT.read_text()
    heldout_bits = [norm(s) for s in re.split(r"\n+", heldout)
                    if len(norm(s)) >= 30]
    heldout_bits += [norm(s) for s in re.split(r"(?<=[.!?])\s+", heldout)
                     if len(norm(s)) >= 30]
    heldout_norm = norm(heldout)

    def screened_out_common(text):
        """Checks (a): probe wording and heldout overlap, for any row."""
        n = norm(text)
        for q in forbidden_questions:
            if q and re.search(r"(?<!\w)" + re.escape(q) + r"(?!\w)", n):
                return "contains probe question (phrase match)"
        for bit in heldout_bits:
            if bit in n or n in bit:
                return "overlaps eval/heldout_text.txt"
        if n in heldout_norm:
            return "chunk inside eval/heldout_text.txt"
        return None

    def screened_out_replay(text):
        """Check (b): the full v8 screening, replay rows only."""
        n = norm(text)
        for q in forbidden_questions + val_instructions:
            if q and re.search(r"(?<!\w)" + re.escape(q) + r"(?!\w)", n):
                return "contains probe/val question (phrase match)"
        qwords = content_words(text)
        for qw in forbidden_q_words:
            if qw and len(qw & qwords) / len(qw) >= 0.7:
                return ">=70% of probe/val question words present"
        return None

    # --- Sampling ------------------------------------------------------------
    rng = random.Random(args.seed)
    replay, seen = [], set()
    stats = {"candidates": 0, "quality_reject": 0,
             "heading_lines_skipped": 0,
             "screen_reject": 0, "screen_reasons": {}, "duplicate": 0,
             "split_fail": 0}
    attempts = 0
    while len(replay) < N_REPLAY and attempts < 50000:
        attempts += 1
        start = rng.randrange(len(body))
        stats["candidates"] += 1
        text = build_chunk(body, start, stats)
        if not quality_ok(text):
            stats["quality_reject"] += 1
            continue
        first, second = split_chunk(text)
        if not first or not second or len(first) < 80 or len(second) < 80:
            stats["split_fail"] += 1
            continue
        reason = screened_out_common(text)
        if reason is None:
            reason = screened_out_replay(text)
        if reason:
            stats["screen_reject"] += 1
            stats["screen_reasons"][reason] = \
                stats["screen_reasons"].get(reason, 0) + 1
            continue
        k = norm(text)
        if k in seen:
            stats["duplicate"] += 1
            continue
        seen.add(k)
        replay.append({
            "instruction": "Continue the following passage.\n\n" + first,
            "response": second,
            "source": "replay-corpus",
        })
    assert len(replay) == N_REPLAY, \
        f"only sampled {len(replay)} replay rows in {attempts} attempts"

    # No overlap between the v9 rows and the replay rows.
    v9_keys = {key(r) for r in v9_rows}
    assert not any(key(r) in v9_keys for r in replay), \
        "a replay row duplicates a v9 row"

    rows = v9_rows + replay
    assert len(rows) == 188, f"expected 188 merged rows, got {len(rows)}"

    # --- Screening: the probe must stay unseen (v10 pattern) ---------------
    replay_keys = {key(r) for r in replay}
    for i, row in enumerate(rows):
        ni = norm(row["instruction"])
        assert ni not in probe_instructions, \
            f"row {i} instruction equals a probe instruction"
        assert ni not in val_instructions, \
            f"row {i} instruction equals a val instruction"
        blob = (row.get("instruction", "") + "\n"
                + row.get("response", "") + "\n"
                + row.get("context", ""))
        reason = screened_out_common(blob)
        assert reason is None, f"row {i} screened out: {reason}"
        if key(row) in replay_keys:
            reason = screened_out_replay(blob)
            assert reason is None, \
                f"replay row {i} screened out: {reason}"

    # Shuffle with the project seed (trainer also shuffles with seed 42;
    # the shuffle here only fixes file order, which is order-independent
    # for training).
    rng.shuffle(rows)

    with open(OUT, "w") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    assert hashlib.sha256(VAL.read_bytes()).hexdigest() == val_before, \
        "val file changed!"

    # --- Token-length check with the real SmolLM2 tokenizer ------------------
    from tokenizers import Tokenizer
    tok = Tokenizer.from_file(
        str(Path.home() / "workspace" / "models" / "smollm2-360m"
            / "tokenizer.json"))
    max_len = 0
    over = 0
    for row in replay:
        prompt = f"### Instruction:\n{row['instruction']}\n### Response:\n"
        n = (len(tok.encode(prompt, add_special_tokens=False).ids)
             + len(tok.encode(row["response"], add_special_tokens=False).ids)
             + 1)
        max_len = max(max_len, n)
        if n > 256:
            over += 1
    assert over == 0, f"{over} replay rows exceed max-len 256"

    provenance = {
        "dataset": "smollm2-rag-v12-train.jsonl",
        "version": "v12",
        "built": "2026-11-18",
        "builder": "tools/build_v12_data.py",
        "base": {
            "file": "data/finetune/smollm2-rag-v9-train.jsonl",
            "rows": len(v9_rows),
            "note": "v9 train set verbatim (100 instruction rows with "
                    "context + 69 intent rows, including the 6 thanks "
                    "paraphrases)",
        },
        "replay": {
            "source_file": "data/expanded/pg1228.txt",
            "source": "Darwin, On the Origin of Species, First Edition "
                      "1859, public domain, recorded in "
                      "data/expanded/SOURCES.md (entry: 'Origin, First "
                      "Edition 1859, 949,182 chars, sha256 dd09b437…'). "
                      "On-disk file is 934,492 bytes; the SOURCES.md "
                      "char count differs (staging count), recorded here "
                      "for transparency.",
            "source_sha256": origin_sha,
            "source_lines_total": len(origin_lines),
            "body_lines": f"{BODY_START}-{BODY_END - 1} (from "
                          "'INTRODUCTION.' to just before 'INDEX.')",
            "seed": args.seed,
            "rows": len(replay),
            "note": "continuous narrative prose sampled from the body of "
                    "the Origin only — NOT dictionary entries, NOT math "
                    "prose. v10's replay was mostly fragmented Webster's "
                    "dictionary definitions at 24%; v12 tests a "
                    "genuinely different replay hypothesis: plain "
                    "narrative at ~10%.",
            "framing": "instruction = 'Continue the following passage.\\n\\n' "
                       "+ first half of a corpus chunk; response = second "
                       "half; source = 'replay-corpus'",
            "chunk_chars": {"min": CHUNK_MIN, "target": CHUNK_TARGET,
                            "max": CHUNK_MAX},
            "split": "near midpoint at a sentence boundary ('. ') in the "
                     "middle third of the chunk; nearest space fallback",
            "fraction_of_train": round(len(replay) / len(rows), 4),
        },
        "val": {
            "file": "data/finetune/smollm2-rag-v9-val.jsonl",
            "rows": len(val_rows),
            "note": "pinned 8 val rows, UNCHANGED (sha256 verified "
                    "identical before/after this build)",
            "sha256": val_before,
        },
        "totals": {"train_rows": len(rows), "v9_rows": len(v9_rows),
                   "replay_rows": len(replay)},
        "screening": {
            "checked_against": [
                "eval/finetune-probe-v5.jsonl (8 probe questions)",
                "data/finetune/smollm2-rag-v9-val.jsonl (8 val instructions)",
                "eval/heldout_text.txt (lines and sentences >= 30 chars)",
            ],
            "rule": "two standards (same as build_v10_data.py). All "
                    "rows: no train instruction may equal (normalized) "
                    "any probe or val instruction; no probe question may "
                    "appear as a phrase in any row; no heldout_text.txt "
                    "line/sentence (>= 30 chars) may appear in any row. "
                    "Replay rows additionally: the full v8 screening "
                    "(val questions as phrases, >=70% of a probe/val "
                    "question's content words).",
            "candidates_examined": stats["candidates"],
            "quality_rejections": stats["quality_reject"],
            "heading_lines_skipped": stats["heading_lines_skipped"],
            "split_failures": stats["split_fail"],
            "screening_rejections": stats["screen_reject"],
            "screening_rejection_reasons": stats["screen_reasons"],
            "duplicate_rejections": stats["duplicate"],
            "result": "all 188 rows pass — no probe wording, no val "
                      "instruction as a train instruction, no "
                      "heldout_text.txt overlap",
        },
        "token_check": {
            "tokenizer": "SmolLM2 tokenizer.json (tokenizers 0.23.3)",
            "max_len": 256,
            "replay_rows_checked": len(replay),
            "max_tokenized_length": max_len,
            "rows_over_max_len": over,
        },
        "training": {
            "recipe": "v9 exact settings: rank 16, alpha 32, targets "
                      "q,k,v,o, LR 2e-4, AdamW, constant LR, 12 epochs, "
                      "batch 2, grad-accum 2, seed 42, --save-every 25, "
                      "from the BASE model. Single-factor change vs v9: "
                      "the data mixture only (plain-narrative replay at "
                      "~10%). LR stays 2e-4 — NOT combined with v11's "
                      "LR 1e-4.",
            "out": "checkpoints/smollm2-lora-mix-v12/",
        },
        "seed": args.seed,
    }
    with open(str(OUT) + ".json", "w") as f:
        json.dump(provenance, f, indent=2, ensure_ascii=False)

    print(f"v9: {len(v9_rows)}, replay: {len(replay)}, total: {len(rows)}")
    print(f"replay fraction: {len(replay) / len(rows):.4f}")
    print(f"candidates: {stats['candidates']}, quality rejects: "
          f"{stats['quality_reject']}, heading lines skipped: "
          f"{stats['heading_lines_skipped']}, split fails: "
          f"{stats['split_fail']}, "
          f"screen rejects: {stats['screen_reject']} "
          f"{stats['screen_reasons']}, duplicates: {stats['duplicate']}")
    print(f"max replay tokenized length: {max_len} (limit 256), over: {over}")
    print("screening: all 188 rows pass (no probe/val/heldout overlap)")
    print(f"wrote {OUT} and {OUT}.json")


if __name__ == "__main__":
    main()
