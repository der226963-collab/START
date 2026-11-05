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

## Python, added 2026-11-04 (Eric: "Implement all sources you find viable and push")
Assembled by a subagent, independently verified
(chars + byte SHA-256 against provenance, separator
counts = file counts) before push. Combined code
corpus after this batch: 7,124,330 chars, 13 files,
sha256 b6fb4d79c0c19b17842a64766354f9e9188b12526e9628c1abaefa7730aaf5e9.
- python_docs.txt — Python official documentation,
  python/cpython branch main: Tutorial (17 files),
  Language Reference (10), Python-focused How-To
  guides (15), 42 files total, 1,289,825 chars,
  sha256 1182d7afb7c94b70…. Licence PSF License
  Version 2; documentation code additionally dual
  PSF / 0BSD from Python 3.8.6. Library reference
  NOT included (scope was tutorial + reference +
  how-to); C-extension how-tos and legacy porting
  guides excluded from the how-to subset.
- think_python.txt — Think Python, 2nd edition,
  Allen B. Downey, AllenDowney/ThinkPython2,
  22 chapters, 436,543 chars, sha256 77163303ed3d74b1….
  Licence CC BY-NC 3.0 Unported (book text, from
  book/book.tex header; repo code MIT, © 2017).
- python_for_everybody.txt — Python for Everybody
  (Exploring Data Using Python 3), Charles Severance,
  csev/py4e book3/AB-copyright.mkd, preface + ch. 1–16,
  17 files, 381,237 chars, sha256 bb67a25fe50f5ac5….
  Licence CC BY-NC-SA 3.0 Unported. Overlap with
  Think Python expected (it is a remix); added value
  is regex, network, web services, objects, databases,
  visualisation.
- dive_into_python3.txt — Dive Into Python 3, Mark
  Pilgrim, diveintomark/diveintopython3, 18 files,
  638,137 decoded chars, byte sha256 662852fa0a3c3a5e….
  Licence CC BY-SA 3.0 (prose/graphics; original code
  MIT; stdlib code PSF 2.0; chardet LGPL 2.1+).
  Counting note: text-mode recount gives 636,328
  chars because universal-newline translation
  collapses 1,809 CR-LF sequences; byte SHA is
  authoritative.
- cpython_stdlib.txt — CPython standard library,
  curated, python/cpython Lib/: dataclasses, functools,
  heapq, bisect, contextlib, enum, json, textwrap,
  string, statistics, copy, pprint, collections,
  pathlib, 14 modules, 511,653 chars, sha256
  023879c0ddecb341…. Licence PSF License Version 2.
  Docstrings intact; tests, generated files, C
  modules excluded.
- automate_boring_stuff_3e.txt — Automate the Boring
  Stuff with Python, 3rd edition, Al Sweigart, No
  Starch Press, official site automatetheboringstuff.com/3e/,
  Chapter 0 + Chapters 1–24 + Appendices A–B,
  27 sections, 1,145,046 chars, sha256
  bba9017608b0dbfb30ab5a670cac4993504735f5843eeecaaf26ec68a260c61d.
  Licence CC BY-NC-SA 4.0 International, © 2025.
  This SUPERSEDES the 2nd edition below, at Eric's
  2026-11-04 direction ("work with the official 3rd
  edition, it may have updates that are more
  important"): 3e is renumbered throughout (e.g.
  Debugging now Ch. 5), and adds Ch. 12 Command
  Line Programs, Ch. 16 SQLite Databases, Ch. 21
  Graphs/Matplotlib, Ch. 22 Recognizing Text in
  Images, Ch. 24 Text-to-Speech/Speech Recognition,
  plus an AI/LLMs section in Ch. 0. Caveats in
  provenance: Ch. 22's sample LLM prompt text is
  missing from the fetched page (output included);
  Appendix B ends at the Ch. 24 answers, index
  excluded. Verified: SHA + 27 separators match
  provenance, 0 chapters failed, no 429 hit.
- SUPERSEDED, 2nd edition partial — Automate the
  Boring Stuff, 2nd edition, Al Sweigart, licence
  CC BY-NC-SA 3.0 United States, © 2020 (page also
  carries No Starch "All rights reserved" boilerplate
  above the CC line, the operative grant for the
  online edition). Only 18 of 24 sections were
  fetched from the official site before a browser
  429 rate limit stopped the work (672,358 chars,
  sha256 7c1d6278…); a 2e mirror search and a
  mirror-verification worker were started, then
  cancelled when Eric directed switching to 3e.
  The partial file and its part files are kept in
  data/code/superseded_2e/ (not in the corpus —
  assemble_code.py only reads data/code/*.txt),
  and are NOT pushed as the ATBS source.

## Original advanced Python, written for START, 2026-11-04
- python_advanced_original.txt — 10 original chapters,
  18,997 chars, sha256 20673ee3d5b7e648fefa69c81f6995f06358a6a0b58ee82236da96fc05d3df28.
  Written at Eric's direction to create genuine
  material from facts only from the books that
  cannot be used (notably Fluent Python, CPython
  Internals, and the ND-licensed Cosmic Python).
  Method, recorded in provenance: topics only,
  no book text, chapter order, or distinctive
  book example reproduced; grounded in PSF
  documentation and the standard library; all
  code examples written for this file and run
  to pass on 2026-11-04. Chapters: data model /
  special methods, sequences and hashing,
  first-class functions and decorators,
  descriptors and properties, metaclasses and
  class creation, iterators / generators /
  coroutines, context managers, typing,
  performance / memory / __slots__, CPython
  compilation pipeline. This is original to
  this project, not a paraphrase of any book.

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
