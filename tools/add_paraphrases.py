"""Append paraphrase pairs to data/instructions.txt.

Reads data/paraphrases_v6.json, looks up each original question's
response in data/instructions.txt, and appends a new
"### Instruction: / ### Response:" block with the paraphrased
question and the same response.

Safety checks (fail loudly instead of silently corrupting the data):
- every "original" must match exactly one existing instruction pair;
- no paraphrase may duplicate an existing instruction question;
- no paraphrase may match a held-out val instruction
  (tools/build_finetune_data.py VAL_INSTRUCTIONS);
- no paraphrase may match a probe question in
  eval/finetune-probe-v5.jsonl (the probe must stay unseen).

Usage:
  python tools/add_paraphrases.py [--dry-run]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.build_finetune_data import parse_instructions, VAL_INSTRUCTIONS  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    instr_path = ROOT / "data" / "instructions.txt"
    pairs = parse_instructions(instr_path)
    by_question = {q: a for q, a in pairs}

    para_path = ROOT / "data" / "paraphrases_v6.json"
    data = json.loads(para_path.read_text())
    entries = data["paraphrases"]

    probe_path = ROOT / "eval" / "finetune-probe-v5.jsonl"
    probe_qs = set()
    if probe_path.exists():
        for line in probe_path.read_text().splitlines():
            if line.strip():
                probe_qs.add(json.loads(line)["instruction"])

    new_blocks = []
    for e in entries:
        orig, para = e["original"], e["paraphrase"]
        if orig not in by_question:
            raise SystemExit(f"original not found in instructions.txt: {orig!r}")
        if para in by_question:
            raise SystemExit(f"paraphrase duplicates an existing question: {para!r}")
        if para in VAL_INSTRUCTIONS:
            raise SystemExit(f"paraphrase collides with a held-out val question: {para!r}")
        if para in probe_qs:
            raise SystemExit(f"paraphrase collides with a probe question: {para!r}")
        if any(para == b[0] for b in new_blocks):
            raise SystemExit(f"duplicate paraphrase in the file: {para!r}")
        new_blocks.append((para, by_question[orig]))

    print(f"paraphrases to add: {len(new_blocks)}")
    print(f"existing pairs: {len(pairs)} -> {len(pairs) + len(new_blocks)} after append")
    print(f"probe questions checked against: {len(probe_qs)}")
    if args.dry_run:
        print("dry run: no changes written")
        return

    with open(instr_path, "a") as f:
        for q, a in new_blocks:
            f.write(f"\n### Instruction:\n{q}\n### Response:\n{a}\n")

    # Re-parse to confirm the file is still valid.
    pairs_after = parse_instructions(instr_path)
    assert len(pairs_after) == len(pairs) + len(new_blocks), (
        f"expected {len(pairs) + len(new_blocks)} pairs after append, "
        f"got {len(pairs_after)}")
    print(f"appended. instructions.txt now has {len(pairs_after)} pairs.")


if __name__ == "__main__":
    main()
