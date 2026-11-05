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

## Advanced books, added 2026-11-04 (Eric: "Implement all of those and push")
Assembled from each repo's src/SUMMARY.md order, branch
main, minimal cleaning only, provenance .json per book
with full file lists. All counts/SHAs independently
verified against provenance before push. Combined code
corpus after this batch: 3,868,749 chars, 8 files,
sha256 ec9164ec0ca267d8c83f8ebe7755e87c53f4a6bfa68e1d62c92e0cc4086409a1.
- reference.txt — The Rust Reference, rust-lang/reference,
  120 files, 1,118,649 chars, sha256 5ce2a8a59d573aac42e95c93782150c545fc3d248e8d991c754b4df99fb146c0.
  Licence MIT / Apache 2.0.
- rustonomicon.txt — The Rustonomicon, rust-lang/nomicon,
  63 files, 305,832 chars, sha256 af7469d7fcd587a70f23aeda689efb7b1e0d3c0e922db994cbb941d9344b68e2.
  Licence MIT. Note: an incomplete draft per its own docs.
- async_book.txt — Asynchronous Programming in Rust,
  rust-lang/async-book, 46 files, 242,367 chars,
  sha256 7ec0e50d34b1d098294a88cd979a64447831296925f71151371d0aa0aaa624c8.
  Licence MIT, Copyright (c) 2018 Aaron Turon.
- rust_cookbook.txt — Rust Cookbook, rust-lang-nursery/rust-cookbook,
  118 SUMMARY files, 605,853 chars, sha256 a9fce2dadad8dbf7a4d22bd0d40c63f1a6f63d0381620adcf287cbc90d00a9da.
  Licence CC0 1.0. Adaptation, recorded in provenance:
  SUMMARY pages are mostly mdBook {{#include}} stubs, so
  includes were expanded recursively mdBook-style
  (423 fragments, 0 failed) — a SUMMARY-only assembly
  was only 145,021 chars and would have discarded the
  recipe bodies. Baseline SUMMARY-only SHA recorded
  in provenance under cookbook_include_expansion.
- embedded_book.txt — The Embedded Rust Book, rust-embedded/book,
  44 files, 218,890 chars, sha256 86b28a998a5ebcf5ef0e92e2c9a228dad12b62a18df0d915f3746314d0ad3d0b.
  Licence MIT.
- api_guidelines.txt — Rust API Guidelines, rust-lang/api-guidelines,
  14 files, 92,140 chars, sha256 061fc703ccc978195a25034d7ec5cd9c2ad79f2996edd0fffdb5dadb4329e0c3.
  Licence MIT / Apache 2.0.
- rust_design_patterns.txt — Rust Design Patterns, rust-unofficial/patterns,
  50 files, 165,486 chars, sha256 e5848e4e6b09ea999e826d6cf578cf360b6c144f8b4c9d36d7bcf644a6de06c7.
  Licence MPL 2.0 (permissive, modified files stay MPL —
  recorded here, unlike the MIT/Apache books above).

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
