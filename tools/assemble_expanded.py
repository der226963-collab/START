"""Assemble expanded, openly licensed training text into one file.

Usage: python tools/assemble_expanded.py
Reads data/expanded/*.txt (source files downloaded verbatim),
strips Project Gutenberg header/footer markers when present,
writes data/expanded_corpus.txt with a source separator before
each book, and prints per-file and total character counts.

This script does NOT download anything and does NOT change the
planning calculation layer. It only assembles text that was
already verified as public domain / CC BY-SA in
data/expanded/SOURCES.md. It is local-only until Eric approves
a push.
"""
import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "expanded"
OUT = ROOT / "data" / "expanded_corpus.txt"

START = re.compile(r"\*\*\* START OF (THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*", re.S)
END = re.compile(r"\*\*\* END OF (THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*", re.S)


def clean(text):
    m = START.search(text)
    if m:
        text = text[m.end():]
    m = END.search(text)
    if m:
        text = text[:m.start()]
    return text.strip() + "\n"


def main():
    files = sorted(SRC.glob("*.txt"))
    if not files:
        raise SystemExit(f"No .txt files in {SRC}")
    parts = []
    total = 0
    for f in files:
        raw = f.read_text(errors="replace")
        body = clean(raw)
        sha = hashlib.sha256(body.encode()).hexdigest()
        print(f"{f.name}: raw {len(raw):,} chars, cleaned {len(body):,} chars, sha256 {sha[:16]}...")
        parts.append(f"\n--- SOURCE: {f.name} ---\n" + body)
        total += len(body)
    OUT.write_text("".join(parts))
    print(f"Wrote {OUT} : {total:,} cleaned characters from {len(files)} files")


if __name__ == "__main__":
    main()
