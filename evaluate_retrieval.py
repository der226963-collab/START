"""Evaluate retrieval + SmolLM2 generation on task questions.

Loads the base model (or a LoRA adapter with --adapter), the
retrieval knowledge base from data/instructions.txt, and a JSONL
test set (val or probe). For each question: retrieve the best fact;
if its score clears --threshold, prepend it as a ### Context: block;
otherwise use the plain prompt. Generate greedily and score strict
exact-match (completion starts with the expected response).

Also prints the retrieval ranking (top 3) for each question, so
retrieval quality and generation quality can be judged separately:
a wrong answer with the right fact retrieved is a generation
problem; a wrong answer with the wrong fact retrieved is a
retrieval problem.

The probe file must stay a test set only. It is never loaded as a
knowledge base; retrieval earns its score on phrasings it has never
seen.

Usage:
  python evaluate_retrieval.py --data eval/finetune-probe-v5.jsonl
  python evaluate_retrieval.py --adapter checkpoints/smollm2-lora-mix-v3/checkpoint.pt --data data/finetune/smollm2-mix-val.jsonl
"""
import argparse
import json
from pathlib import Path

import torch

from mini_ai.gpt.lora import apply_adapter_checkpoint
from mini_ai.gpt.smollm2 import load_pretrained, load_tokenizer
from mini_ai.retrieval import INTENT_THRESHOLD, load_kb, match_intent

DEFAULT_DIR = "/home/hatch/workspace/models/smollm2-360m"


def build_prompt(question, facts):
    """Prompt with the retrieved fact(s) as context, or plain if none."""
    if facts:
        ctx = "\n".join(f["response"] for f in facts)
        return f"### Context:\n{ctx}\n\n### Instruction:\n{question}\n### Response:\n"
    return f"### Instruction:\n{question}\n### Response:\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", default=DEFAULT_DIR)
    ap.add_argument("--adapter", default=None,
                    help="Path to a LoRA checkpoint.pt; omit for base model.")
    ap.add_argument("--data", default="data/finetune/smollm2-mix-val.jsonl")
    ap.add_argument("--kb", default="data/instructions.txt")
    ap.add_argument("--limit", type=int, default=0, help="0 = all")
    ap.add_argument("--max-new", type=int, default=120)
    ap.add_argument("--temperature", type=float, default=0.0,
                    help="0 = greedy (deterministic)")
    ap.add_argument("--max-context", type=int, default=512)
    ap.add_argument("--threshold", type=float, default=0.2,
                    help="Minimum retrieval score to use the fact; "
                         "below this, answer with no context.")
    ap.add_argument("--top-k", type=int, default=1,
                    help="How many retrieved facts to put in context.")
    ap.add_argument("--intent-threshold", type=float, default=INTENT_THRESHOLD,
                    help="Minimum intent overlap to treat the question "
                         "as a known intent (no retrieval).")
    args = ap.parse_args()

    kb = load_kb(args.kb)
    print(f"knowledge base: {len(kb)} facts from {args.kb}")

    model, config = load_pretrained(args.model_dir, dtype=torch.bfloat16)
    if args.adapter:
        apply_adapter_checkpoint(model, args.adapter)
        print(f"adapter loaded from {args.adapter}")
    else:
        print("base model (no adapter)")
    tokenizer = load_tokenizer(args.model_dir)
    model.eval()

    rows = [json.loads(l) for l in Path(args.data).read_text().splitlines() if l.strip()]
    if args.limit:
        rows = rows[:args.limit]

    exact = 0
    retrieved_right = 0
    for i, row in enumerate(rows):
        q = row["instruction"]
        expected = row["response"].strip()
        # Intent gate: a known intent is answered by the model itself,
        # not by retrieval. Otherwise a one-word intent like "plan"
        # retrieves the plan-checking fact and derails the answer.
        intent, iscore, iutt = match_intent(q, threshold=args.intent_threshold)
        ranked = kb.retrieve(q, top_k=max(args.top_k, 3)) if not intent else []
        best = ranked[0] if ranked else None
        use = [f for s, _, _, f in ranked[:args.top_k]
               if s >= args.threshold]
        prompt = build_prompt(q, use)
        ids = tokenizer.encode(prompt, add_special_tokens=False).ids
        idx = torch.tensor([ids], dtype=torch.long)
        with torch.no_grad():
            out = model.generate(idx, max_new_tokens=args.max_new,
                                 temperature=args.temperature,
                                 eos_id=config.eos_token_id,
                                 max_context=args.max_context)
        full = tokenizer.decode(out[0].tolist(), skip_special_tokens=True)
        completion = full[len(prompt):].strip()
        is_exact = bool(completion) and completion.startswith(expected)
        if is_exact:
            exact += 1
        # Did retrieval find the fact whose response is the expected one?
        if best and best[3]["response"] == expected:
            retrieved_right += 1
        print(f"--- [{i + 1}/{len(rows)}] source={row['source']} "
              f"exact={'YES' if is_exact else 'no'} "
              f"retrieved={'YES' if best and best[3]['response'] == expected else 'no'}"
              + (f" intent={intent} ({iscore:.2f})" if intent else ""))
        print(f"Q: {q}")
        for rank, (s, qr, rr, fact) in enumerate(ranked, 1):
            print(f"  rank{rank} score={s:.2f} q={qr:.2f} r={rr:.2f} "
                  f"fact={fact['response'][:90]}")
        print(f"expected: {expected[:300]}")
        print(f"got:      {completion[:300]}")
        print()
    print(f"exact-match: {exact}/{len(rows)}")
    print(f"retrieval found the right fact: {retrieved_right}/{len(rows)}")


if __name__ == "__main__":
    main()
