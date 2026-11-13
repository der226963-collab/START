# Expanded corpus parts

The assembled corpus (data/expanded_corpus.txt) is too large for a single
push, so it is stored here in parts, each under 1,900,000 bytes.

Reassemble in order:

```
cat data/expanded_corpus_parts/part-*.txt > data/expanded_corpus.txt
```

Total: 47,073,268 bytes in 34 parts.
Parts are split at line boundaries. See data/expanded/SOURCES.md for
the source books, licences, and per-source character counts.
