"""Build the RAG fine-tuning dataset (v7): instruction examples carry
their fact as context, so the model learns to ground its answer on
retrieved text instead of memorising it.

Sources: the same train/val split as tools/build_finetune_data.py
(same pinned 8 val examples, so scores stay comparable). For each
instruction example, the context is the fact it belongs to — the KB
fact whose response matches the example's response. This is a direct
lookup, not retrieval: training must teach grounding on the CORRECT
fact, and retrieval can pick the wrong fact for an ambiguous
question (care-kinds). At eval time the context comes from real
retrieval (evaluate_retrieval.py), which is the honest test.

Intent examples get no context, matching inference: the intent gate
means intent questions are answered with no retrieval.

Output (JSONL):
  {"instruction": str, "response": str, "source": str, "context": str}
where context is the fact response for instructions, "" for intents.

Usage:
  python tools/build_rag_data.py [--out-dir data/finetune]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mini_ai.retrieval import load_kb  # noqa: E402
from tools.build_finetune_data import build as build_base  # noqa: E402


def build():
    train, val = build_base()
    kb = load_kb(str(ROOT / "data" / "instructions.txt"))
    by_response = {fact["response"]: fact for fact in kb.facts}

    def add_context(rows):
        out = []
        for row in rows:
            row = dict(row)
            if row["source"] == "instructions":
                fact = by_response.get(row["response"])
                assert fact is not None, (
                    f"instruction response not a KB fact: {row['instruction'][:60]!r}")
                row["context"] = fact["response"]
            else:
                row["context"] = ""
            out.append(row)
        return out

    return add_context(train), add_context(val)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="data/finetune")
    args = ap.parse_args()

    train, val = build()
    out_dir = ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    train_path = out_dir / "smollm2-rag-train.jsonl"
    val_path = out_dir / "smollm2-rag-val.jsonl"
    for path, rows in ((train_path, train), (val_path, val)):
        with open(path, "w") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    n_ctx = sum(1 for r in train if r["context"])
    print(f"train: {len(train)} examples -> {train_path}")
    print(f"  {n_ctx} with context, {len(train) - n_ctx} without (intents)")
    print(f"val:   {len(val)} examples -> {val_path}")
    print(f"  {sum(1 for r in val if r['context'])} with context, "
          f"{sum(1 for r in val if not r['context'])} without (intents)")
    # The val set must be the same 8 pinned examples as the base split.
    base_train, base_val = build_base()
    assert {r["instruction"] for r in val} == {r["instruction"] for r in base_val}, \
        "RAG val set differs from the pinned val set"
    print("val set identical to the pinned 8.")


if __name__ == "__main__":
    main()
