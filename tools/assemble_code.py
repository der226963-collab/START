"""Assemble the separate code corpus.

Why separate (2026-11-04 decision): programming languages
are now in scope, but mixing them into the textbook corpus
at whatever ratio their file sizes happen to give (Rust
was ~5%) dilutes them to nothing — the 100-step medium
run gave Rust loss 5.22, worse than overall 4.86, and no
Rust generation. Code sources live in data/code/, textbook
sources stay in data/expanded/, and train_gpt.py mixes
them at an explicit --code-ratio instead of inheriting
file sizes.

This script mirrors tools/assemble_expanded.py for code:
reads data/code/*.txt, writes data/code_corpus.txt with
a source separator before each file, prints per-file and
total counts. It does NOT check licences — every file in
data/code/ must already be verified openly licensed and
recorded in data/code/SOURCES.md by a human, before
assembly. It does NOT write over a source file.
"""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "code"
OUT = ROOT / "data" / "code_corpus.txt"


def main():
    files = sorted(SRC.glob("*.txt"))
    if not files:
        raise SystemExit(f"No .txt files in {SRC}")
    parts = []
    total = 0
    for f in files:
        raw = f.read_text(errors="replace")
        body = raw.strip() + "\n"
        sha = hashlib.sha256(body.encode()).hexdigest()
        print(f"{f.name}: raw {len(raw):,} chars, cleaned {len(body):,} chars, sha256 {sha[:16]}...")
        parts.append(f"\n--- SOURCE: {f.name} ---\n" + body)
        total += len(body)
    OUT.write_text("".join(parts))
    print(f"Wrote {OUT} : {total:,} cleaned characters from {len(files)} files")


if __name__ == "__main__":
    main()
