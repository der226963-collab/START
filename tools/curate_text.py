"""Curate training text the SmolLM way, with our own code.

Hugging Face emphasis (2026-11-04): the Hugging Face repos
checked for this batch are all Apache 2.0, so their code
*can* be copied with the licence notice kept — tokenizers,
transformers, datasets, and smollm all carry Apache 2.0.
We still did not copy them here, for two reasons that are
recorded, not assumed:
  - tokenizers is Rust. It cannot be dropped into this
    stdlib Python project, so mini_ai/gpt/bpe.py now has
    an original incremental BPE trainer that produces the
    same merges, fast (see its docstring).
  - smollm's repo is mostly model cards and transformers
    usage, not a curation script to copy. Its *idea* —
    small models trained on curated, textbook-quality
    text, deduplicated and filtered, rather than on raw
    scraped text — is what this tool implements, in
    original Python, for our own openly licensed files.

What this tool does, and does not do:
  - Splits text into paragraphs, drops exact duplicates
    (normalised hash, first occurrence kept), drops
    paragraphs that are too short, mostly non-alphabetic,
    or mostly very short tokens (navigation/menu-like).
  - It does NOT check licences. Every input file must
    already be verified openly licensed and recorded in
    data/expanded/SOURCES.md by a human, before curation.
  - It does NOT write over a source file. It writes a
    new output file, so the original stays intact.
  - It is a tool, not a training-data decision: curated
    output is not added to training until a human
    approves it, same as any other data batch.

Usage:
  python tools/curate_text.py data/expanded/foo.txt /tmp/foo_curated.txt
"""
import hashlib
import re
import sys
from pathlib import Path


def _normalise(paragraph):
    return re.sub(r"\s+", " ", paragraph.strip().lower())


def _is_keepable(paragraph):
    text = paragraph.strip()
    if len(text) < 50:
        return False
    letters = sum(c.isalpha() for c in text)
    if letters / max(1, len(text)) < 0.7:
        return False
    words = text.split()
    if not words:
        return False
    short = sum(1 for w in words if len(w) < 3)
    if short / len(words) > 0.5:
        return False
    return True


def curate(text):
    """Return (curated_text, kept, dropped_duplicate, dropped_filter)."""
    paragraphs = re.split(r"\n\s*\n", text)
    seen = set()
    kept = []
    dup = filt = 0
    for para in paragraphs:
        norm = _normalise(para)
        if not norm:
            continue
        key = hashlib.sha256(norm.encode()).hexdigest()
        if key in seen:
            dup += 1
            continue
        seen.add(key)
        if not _is_keepable(para):
            filt += 1
            continue
        kept.append(para.strip())
    return "\n\n".join(kept) + ("\n" if kept else ""), len(kept), dup, filt


def main(argv):
    if len(argv) != 3:
        raise SystemExit("Usage: python tools/curate_text.py <input.txt> <output.txt>")
    src, dst = Path(argv[1]), Path(argv[2])
    out, kept, dup, filt = curate(src.read_text(errors="replace"))
    dst.write_text(out)
    print(f"{src}: kept {kept} paragraphs, dropped {dup} duplicates, {filt} filtered")
    print(f"Wrote {dst}: {len(out):,} chars (original {len(src.read_text(errors='replace')):,} chars)")


if __name__ == "__main__":
    main(sys.argv)
