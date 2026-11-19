"""Generate text from the SmolLM2-360M pretrained model.

Usage:
  python generate_smollm2.py --prompt "The garden " --length 150
  python generate_smollm2.py --temperature 0.7

The model is HuggingFaceTB/SmolLM2-360M (Apache 2.0), loaded with our
own code in mini_ai/gpt/smollm2.py. This is a language assistant,
not a planner or a decider. Treat its output as draft text to be
checked by people, not as a plan or an allocation.
"""
import argparse

import torch

from mini_ai.gpt.lora import apply_adapter_checkpoint
from mini_ai.gpt.smollm2 import load_pretrained, load_tokenizer

DEFAULT_DIR = "/home/hatch/workspace/models/smollm2-360m"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", default=DEFAULT_DIR)
    parser.add_argument("--prompt", default="The garden ")
    parser.add_argument("--length", type=int, default=150)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--repetition-penalty", type=float, default=1.0,
                        help="Repetition penalty on generated tokens "
                             "(CTRL/HF rule); 1.0 = off, higher values "
                             "discourage repeating tokens.")
    parser.add_argument("--no-repeat-ngram", type=int, default=0,
                        help="No-repeat n-gram size: ban any token that "
                             "would complete an n-gram of this size "
                             "already generated; 0 = off, 2 or more to "
                             "enable.")
    parser.add_argument("--min-new-tokens", type=int, default=0,
                        help="Minimum new tokens: suppress the EOS token "
                             "for the first N generated tokens, so the "
                             "model cannot stop immediately; 0 = off.")
    parser.add_argument("--max-context", type=int, default=1024)
    parser.add_argument("--dtype", choices=["bf16", "fp32"], default="bf16")
    parser.add_argument("--adapter", default=None,
                        help="Path to a LoRA checkpoint.pt (from "
                             "train_smollm2_lora.py) to generate with the "
                             "fine-tuned model instead of the base model.")
    args = parser.parse_args()

    dtype = torch.bfloat16 if args.dtype == "bf16" else torch.float32
    model, config = load_pretrained(args.model_dir, dtype=dtype)
    if args.adapter:
        apply_adapter_checkpoint(model, args.adapter)
    tokenizer = load_tokenizer(args.model_dir)
    ids = tokenizer.encode(args.prompt, add_special_tokens=False).ids
    idx = torch.tensor([ids], dtype=torch.long)
    out = model.generate(idx, max_new_tokens=args.length,
                         temperature=args.temperature,
                         eos_id=config.eos_token_id,
                         max_context=args.max_context,
                         repetition_penalty=args.repetition_penalty,
                         no_repeat_ngram_size=args.no_repeat_ngram,
                         min_new_tokens=args.min_new_tokens)
    print(tokenizer.decode(out[0].tolist(), skip_special_tokens=True))


if __name__ == "__main__":
    main()
