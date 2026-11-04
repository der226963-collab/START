"""Split data/expanded_corpus.txt into parts under a byte limit.

The push tool refuses a single file over ~2,023,884 bytes, and the
assembled corpus is now 17+ MB. So the corpus is pushed as parts,
not as one file. Reassemble with: cat data/expanded_corpus_parts/part-*.txt > data/expanded_corpus.txt
Parts are split at line boundaries, so no line is cut in half.
Local training still uses data/expanded_corpus.txt directly.
"""
import hashlib, json, pathlib, sys

LIMIT = 1_400_000  # bytes, safely under the observed push limits (1.58-2.02 MB, varies)
SRC = pathlib.Path(__file__).resolve().parent.parent / "data" / "expanded_corpus.txt"
OUT = pathlib.Path(__file__).resolve().parent.parent / "data" / "expanded_corpus_parts"

def main():
    data = SRC.read_bytes()
    OUT.mkdir(exist_ok=True)
    for old in OUT.glob("part-*.txt"):
        old.unlink()
    parts, cur, idx = [], bytearray(), 1
    for line in data.splitlines(keepends=True):
        if cur and len(cur) + len(line) > LIMIT:
            parts.append(bytes(cur)); cur = bytearray()
        cur += line
    if cur:
        parts.append(bytes(cur))
    manifest = []
    for i, part in enumerate(parts, 1):
        name = f"part-{i:02d}.txt"
        (OUT / name).write_bytes(part)
        manifest.append({"file": name, "bytes": len(part), "sha256": hashlib.sha256(part).hexdigest()})
    (OUT / "README.md").write_text(
        "# Expanded corpus parts\n\n"
        "The assembled corpus (data/expanded_corpus.txt) is too large for a single\n"
        "push, so it is stored here in parts, each under 1,900,000 bytes.\n\n"
        "Reassemble in order:\n\n"
        "```\ncat data/expanded_corpus_parts/part-*.txt > data/expanded_corpus.txt\n```\n\n"
        f"Total: {len(data):,} bytes in {len(parts)} parts.\n"
        "Parts are split at line boundaries. See data/expanded/SOURCES.md for\n"
        "the source books, licences, and per-source character counts.\n"
    )
    (OUT / "manifest.json").write_text(json.dumps({"total_bytes": len(data), "parts": manifest}, indent=2))
    print(f"Split {len(data):,} bytes into {len(parts)} parts, max {max(len(p) for p in parts):,} bytes")

if __name__ == "__main__":
    main()
