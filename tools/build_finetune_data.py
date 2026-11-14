"""Build the SmolLM2 narrow fine-tuning dataset: a mix of instruction
pairs and intent examples, in one unified format.

Sources (all this project's own data, no external text):
- data/instructions.txt: ### Instruction: / ### Response: pairs.
- mini_ai/data.py INTENTS + RESPONSES: each example utterance maps
  to its intent's canned response.

Output (JSONL, one example per line):
  {"instruction": str, "response": str, "source": str}
where source is "instructions" or "intent:<label>".

A small validation split is held out for a generalisation check:
the 8 examples in VAL_INSTRUCTIONS (2 instruction pairs + 1 example
per intent). They are pinned by exact instruction text, so adding
new training data can never change which examples are held out —
the val file stays identical across rebuilds and the exact-match
scores stay comparable between adapter versions.

Usage:
  python tools/build_finetune_data.py [--out-dir data/finetune]
"""
import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mini_ai.data import INTENTS, RESPONSES  # noqa: E402

# Pinned validation set: the same 8 examples v1-v4 were tested on.
# Never add a training example with one of these instruction strings.
VAL_INSTRUCTIONS = {
    "How should labour and care be shared?",
    "What is unpaid care work?",
    "that helps",
    "plan this with me",
    "who decides",
    "how do you work",
    "hi",
    "goodbye",
}


def parse_instructions(path):
    """Parse data/instructions.txt into (instruction, response) pairs."""
    text = Path(path).read_text()
    pairs = []
    # Split on the "### Instruction:" marker; each block holds one pair.
    blocks = text.split("### Instruction:")
    for block in blocks[1:]:
        if "### Response:" not in block:
            raise ValueError(f"instruction block without a response: {block[:80]!r}")
        q, a = block.split("### Response:", 1)
        q = q.strip()
        a = a.strip()
        if not q or not a:
            raise ValueError(f"empty instruction or response: {block[:80]!r}")
        pairs.append((q, a))
    return pairs


def build(seed=42):
    rng = random.Random(seed)
    examples = []

    instr_pairs = parse_instructions(ROOT / "data" / "instructions.txt")
    instr = [{"instruction": q, "response": a, "source": "instructions"}
             for q, a in instr_pairs]

    intent = []
    for label, utterances in INTENTS.items():
        resp = RESPONSES[label]
        for u in utterances:
            intent.append({"instruction": u, "response": resp,
                           "source": f"intent:{label}"})

    # Hold out the pinned validation examples; everything else trains.
    all_examples = instr + intent
    val = [ex for ex in all_examples if ex["instruction"] in VAL_INSTRUCTIONS]
    train = [ex for ex in all_examples
             if ex["instruction"] not in VAL_INSTRUCTIONS]
    # The val set must stay exactly the 8 known examples: if a new
    # training utterance ever collides with a val instruction, this
    # fails loudly instead of silently changing the benchmark.
    assert len(val) == 8, f"expected 8 val examples, got {len(val)}"
    assert len({ex["instruction"] for ex in val}) == 8, "duplicate val instruction"
    rng.shuffle(train)
    rng.shuffle(val)
    return train, val


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="data/finetune")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    train, val = build(seed=args.seed)
    out_dir = ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    train_path = out_dir / "smollm2-mix-train.jsonl"
    val_path = out_dir / "smollm2-mix-val.jsonl"
    for path, rows in ((train_path, train), (val_path, val)):
        with open(path, "w") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def counts(rows):
        c = {}
        for r in rows:
            c[r["source"]] = c.get(r["source"], 0) + 1
        return c

    print(f"train: {len(train)} examples -> {train_path}")
    print(f"  {counts(train)}")
    print(f"val:   {len(val)} examples -> {val_path}")
    print(f"  {counts(val)}")
    print("val instructions held out:")
    for r in val:
        print(f"  [{r['source']}] {r['instruction'][:70]}")


if __name__ == "__main__":
    main()
