# Code corpus — sources, licences, and status

Separate from the textbook corpus (data/expanded/), by
Eric's 2026-11-04 decision to use a separate code corpus
with a mixture ratio. Training mixes this corpus with
the textbook corpus at an explicit --code-ratio in
train_gpt.py, instead of inheriting file sizes.

## Rust
- rust_book.txt — The Rust Programming Language, Steve
  Klabnik, Carol Nichols, and Chris Krycho, with
  contributions from the Rust Community, assembled from
  rust-lang/book, branch main, 111 chapter .md files in
  SUMMARY.md order, 1,119,540 chars, sha256
  d33ef85f6ef53c88e4521c0d04508ef8480c8c06013b09f94351f71368dd5e81.
  Licence verified from that repo's LICENSE-MIT: MIT,
  Copyright (c) 2010 The Rust Project Developers; Rust
  project is dual MIT / Apache 2.0. Provenance in
  rust_book.txt.json. Moved here from data/expanded/
  on 2026-11-04 when the code corpus was separated;
  the textbook corpus reverted to its pre-Rust total
  (19,767,249 chars, 16 files) after the move.

## Not yet added
- C and Java: flagged by Eric as having potential, no
  source verified or added yet. Each will need its own
  licence check and provenance file before assembly.
- Python: the project's own language, and the core
  language alongside Rust. No Python tutorial/code
  source has been added to this corpus yet; the
  project's own Python code (mini_ai/, train_gpt.py)
  is original to this project and is a candidate
  source, but it has not been assembled into a training
  file yet.
