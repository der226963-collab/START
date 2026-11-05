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

## C, added 2026-11-05 (assembled locally, pushed same day)
- cppreference_c.txt — cppreference.com C Reference (C language and C standard library), 44 pages fetched 2026-11-05 from en.cppreference.com (C reference index, C language index, headers index, 9 core language topic pages, all 32 standard library header pages). Licence: CC BY-SA 3.0 Unported / GFDL, verified from https://en.cppreference.com/Cppreference:FAQ (link back to cppreference.com requested; modified content under an equivalent licence). 180,139 chars, SHA-256 dfd3010665d7aff1efb9f1026ca1bed69b3bf5016aee92922e5af91ab3207b7d. Header-level reference only — individual function pages not included.
- build_your_own_lisp.txt — Build Your Own Lisp, Daniel Holden, orangeduck/BuildYourOwnLisp, branch master, commit 01cb0705, Chapters 1-16 + Appendix A + FAQ, 18 sections, 249,444 chars, sha256 e3dc68bad3f116ab8b3e87e031df27df41624834be43bace147ffdd6f4db9205. Licence CC BY-NC-SA 3.0 (book text, verified from the repo README.md and LICENSE.md; repo code is BSD-3 but was not included).
- wikibooks_c_programming.txt — C Programming (Wikibooks), Wikibooks contributors, main page + 245 subpages of the C programming tree, 243 sections, 979,532 chars, sha256 ab013aeffa11e83024d9339c9425b9c58de036a4569bbcbd1b6acac1be592218. Licence CC BY-SA 4.0, dual GFDL (unversioned, no invariant sections), verified from Wikibooks:License. Assembled from the official enwikibooks pages-articles dump (2026-11-05) after the live API returned 429 after 12 pages. Caveats: two stray ]] fragments remain; inline <math> formulae are dropped, leaving gaps in a few prose lines; 17 pages under 200 chars (short stubs).
- little_c_primer.txt — A Little C Primer, Greg Goebel, Wikibooks print version, 20 chapters, 110,524 chars, sha256 b4f957379dcde5adcfa4cb2784f14dca7c16487b0670d057f6219feeb0fa9c0a. Licence CC BY-SA 4.0 / GFDL 1.2+ (Wikibooks version, per the book's own Wikibooks Licensing page). The public-domain original at vectorsite.net/tscpp.html is no longer reachable (domain parked as of 2026-11-05), so the Wikibooks version was used instead. Caveat: 3 '*' characters swallowed by page-text rendering were restored from context (p * p, g * g, /*Define ... */).
- gnu_c_reference_manual.txt — The GNU C Reference Manual, Trevis Rothwell and James Youngman, official v0.2.5 PDF (2015), gnu.org, Title page + Preface + Ch. 1-7 + Appendix A, 10 sections, 149,341 chars, sha256 4e445f7f77e4175f5c076704e8927536e11df20193f7e4c9f95269412458e442. Licence GFDL 1.3 or later, no Invariant Sections, no Front-Cover Texts, no Back-Cover Texts, verified from the manual's own copyright page. GFDL was not in the fetcher's earlier allowed list; included at Eric's 2026-11-05 direction to include all C sources.
- gnu_c_programming_tutorial.txt — The GNU C Programming Tutorial, Edition 4.1, Mark Burgess and Ron Hale-Evans, DePaul mirror PDF (ctut.pdf), Title page + Preface + Ch. 1-24 + Appendices A-G + Bibliography + Glossary + Bits and pieces, 36 sections, 490,377 chars, sha256 51f62f92408014efd55f7378c5789ebe5491e4ca91331977c966097001b15c75. Licence GFDL 1.1 or later, no Invariant Section, Front-Cover Texts "A GNU Manual", verified from the document's own copyright page. GFDL note as above. Caveat: Appendix G, Bibliography and Glossary are "Blah blah blah." stubs in Edition 4.1 itself.
- snefru_learning_c.txt — Snefru: Learning Programming with C, Salma Emara, salma-emara/aps105-book, branch main, in _toc.yml order: cover + preface + chapters 1-15 + appendix, 89 files, 511,481 chars, sha256 65e25005f0c8de5ed529900f0edd97c00c741882ed4aab14ecd8d3b9b15e173b. Licence GPL-3.0, Copyright 2022-2025 Salma Emara, verified from the book's own cover page and the repo LICENSE. Caveat, from the cover page: many parts were written with help from GitHub Copilot, GPT-3.5 and GPT-4.
- modern_c.txt — Modern C, Third Edition (Covers the C23 standard), Jens Gustedt, Manning, ISBN 9781633437777, front matter + chapters 1-21 + appendices A-C + Takeaways + Selected bibliography, 32 sections, 1,182,926 chars, sha256 6eda9085405ba1c4d017bcadcf4e42ecbb3d739241a5bdf8ba848c8a433d0acb. Licence CC BY-NC, verified from the PDF's own front matter ("© 2025 Jens Gustedt… released the manuscript… under a Creative Commons license for non-commercial use (CC BY NC)"). Source PDF was an unofficial mirror (tilde.town/~fiore/tmp/modern-c-third-edition.pdf) of the Manning edition; the author's free HAL version is CC BY-NC-ND 4.0 and was NOT used. Eric directed on 2026-11-05 to use the copy already obtained and push it, knowing the mirror provenance. The 1st edition (CC BY-NC-ND 4.0) was not used.
- cpython_c_source.txt — CPython C source, curated, python/cpython branch main (2026-11-05 snapshot), 13 files (Objects/object.c, listobject.c, dictobject.c, tupleobject.c, boolobject.c, floatobject.c; Include/object.h, listobject.h, dictobject.h, tupleobject.h; Python/errors.c; Modules/_bisectmodule.c, _heapqmodule.c), 747,501 chars, sha256 bb947466232ede246af4a09427a7c9c4e42ffae335043b272e80738ea00855b1. Licence PSF License Version 2, verified from python/cpython LICENSE.
- sqlite_c_source.txt — SQLite C source, curated, sqlite/sqlite branch master (Git mirror of Fossil trunk, 2026-11-05 snapshot), 13 files (src/tokenize.c, util.c, hash.c, printf.c, mem1.c, mem2.c, malloc.c, treeview.c, status.c, fault.c, build.c, vdbeaux.c, sqlite3ext.h), 694,779 chars, sha256 38ba50db02e68c3d5185c74e94f27cfc0f69d9fe7ccff32b3855b52bccbe55af. Licence public domain (SQLite public-domain dedication, verified from the repo README and the dedication header in src/fault.c). Amalgamation excluded (~9 MB, too large).
- linux_kernel_c_source.txt — Linux kernel C source, curated teaching subset, torvalds/linux branch master, 13 files (lib/string.c, vsprintf.c, sort.c, list_sort.c, rbtree.c, radix-tree.c, ctype.c, cmdline.c, hexdump.c, bsearch.c, kstrtox.c; kernel/panic.c, kernel/printk/printk.c), 395,109 chars, sha256 403b9ec6f0a76a4e2f75fc9353e366ffd596c2877681e20c7ba0343d1acc102e. Licence GPL-2.0 WITH Linux-syscall-note, verified from torvalds/linux COPYING.
- musl_c_source.txt — musl libc, curated, ifduyue/musl branch
  master (unofficial mirror of git://git.musl-libc.org/musl),
  commit 7813e9119eb5fe681b6750b8a033a0490bca0941 (HEAD at
  fetch time 2026-11-05), 335 files, 345,899 chars, sha256
  db24418b9cde301ed6a9c21c0aba415448e0cee7ac53195e6e5b377d67e0829d.
  Licence MIT License, verified from that mirror's own
  COPYRIGHT file ("musl as a whole is licensed under the
  following standard MIT license", Copyright © 2005-2020
  Rich Felker, et al.); identical MIT text also verified
  in kraj/musl COPYRIGHT. Contents: all of src/string
  (74 .c), all of src/stdio (116 .c), all of src/stdlib
  (22 .c), all of src/ctype (37 .c), double-precision math
  core (73 .c) plus float/long-double variants of sqrt,
  fabs, floor, ceil and Bessel j0/j1/jn, plus
  src/prng/rand.c and src/malloc/mallocng/malloc.c
  (neither lives in src/stdlib). Excluded: math *_data
  tables and __rem_pio2_large.c, other float/long-double
  math variants, .h data-table headers, arch-specific
  subdirectories. Caveat, from COPYRIGHT: much of the
  math code is derived from Sun/FreBSD sources under
  permissive terms, labelled in the individual files.
  Fetch note: parallel requests hit a transient GitHub
  MCP rate limit; the worker backed off and resumed
  sequentially with a delay, 335 files fetched, 0 failed.
  Assembled 2026-11-05, NOT yet pushed — follows in a
  later push once the parent verifies it.
- Excluded C sources (do not add): Beej's Guide to C (CC BY-NC-ND 3.0), Thinking in C (CC BY-NC-ND 2.5), The C Book (licence convoluted/unclear), K&R, C: A Modern Approach, Learn C the Hard Way (commercial/copyrighted). Modern C 1st edition (CC BY-NC-ND 4.0) also excluded.

## Advanced Python, added 2026-11-05 (assembled locally, pushed same day)
- python_library_reference_a.txt through _f.txt — Python Library Reference, python/cpython branch main, Doc/library/, commit 288cc2bf (2026-11-05 snapshot), all 329 .rst files, 6,150,186 chars total: a 1,190,649 (76 files, sha256 32623ed221010ee2…), b 1,188,397 (77, cf9331ebc85eb49b…), c 1,192,279 (60, e2c2ffcb23485a08…), d 1,196,403 (60, e9863a0d28dcd19f…), e 1,167,340 (42, 9b1c9387deae4fd3…), f 215,118 (14, ee20fa86b6ee1cd8…). Licence PSF License Version 2 (docs code additionally dual PSF/0BSD from 3.8.6), verified from python/cpython's own LICENSE. Split into six ~1.2M-char parts at file boundaries because the full reference is ~6.15M chars and a single file cannot be pushed; no truncation. 21 non-text files excluded.
- python_peps.txt — Python Enhancement Proposals, python/peps, 9 PEPs, 386,304 chars, sha256 19d2ef6dba0237bbe35cc6d655965b89cafca9dc0357aa42f4b12b70ff007729. PEPs 484, 492, 525, 530, 563, 567, 572, 649, 695. Licence: public domain / CC0-1.0-Universal — NOT PSF, verified from each PEP's own Copyright section (484, 492, 525, 530, 563, 567, 572 public domain; 649 and 695 public domain or CC0, whichever is more permissive, per PEP 1 §15). PEP 563 is superseded by 649 and is kept as design history.
- cpython_devguide.txt — CPython Developer Guide, python/devguide branch main, commit d0a9edd4, all 61 .rst pages, 619,468 chars, sha256 79796e833a44d4b9772b1598a40a7f9944dd41f1a8b1a39e75cf54b9cad20d17. Licence CC0 1.0 Universal — NOT PSF, verified from the devguide repo's own LICENSE file.
- cpython_internaldocs.txt — CPython InternalDocs, python/cpython, InternalDocs/ (Doc/internal/ does not exist), all 19 files plus Objects/listsort.txt (timsort, linked from the InternalDocs README), 20 sections, 285,818 chars, sha256 bb233d0559fa1cc63b6ea26e58b5a4393ac34785cb49341cbb7b87a2c8f28346. Licence PSF License Version 2, verified from cpython's LICENSE. 5 PNG diagrams excluded (prose kept).

## Java, added 2026-11-05 (assembled locally, not yet pushed)
- think_java.txt — Think Java: How to Think Like a Computer Scientist, 2nd Edition, Chris Mayfield, ChrisMayfield/ThinkJava2, master, commit 012feca6 (2026-10-29), v7.1.1, Preface + 17 chapters + 5 appendices, 23 sections, 478,603 chars, sha256 7ad8b6c35f3adcf4f8ab8f5ae07291dfb6af46a4bf2d4598c3fa9a17557ea0f8. Licence CC BY-NC-SA 4.0, verified from the book's own front matter (the repo has no LICENSE file despite the README linking one).
- think_data_structures.txt — Think Data Structures: Algorithms and Information Retrieval in Java, Allen B. Downey, AllenDowney/ThinkDataStructures, master, commit f197bff6 (2026-10-10), v1.1.0, all 17 chapters of book/book.tex, 220,711 chars, sha256 b9995dbd9bba92b745efc4cfc1674b0339582863c9674c724abe4cc574832996. Licence CC BY-NC-SA 3.0 Unported for the book text (from the book.tex header); the repo LICENSE is MIT for code.
- javanotes9_part1.txt — Introduction to Programming Using Java, Version 9 (JavaFX Edition), David J. Eck, math.hws.edu/javanotes, May 2022, Ch. 1-7, 50 sections, 1,030,583 chars, sha256 03a6360f899f61c74a8b7a6f00008445ff10767ebcf6ec669ddd030e42dd4ae6. Licence CC BY-NC-SA 4.0, verified from the book's own index page.
- javanotes9_part2.txt — Same book, Ch. 8-13, 31 sections, 919,437 chars, sha256 30c3efe2807ab3ed313ae5022e48bef183384f19b66229f44e923734be69d797. Licence CC BY-NC-SA 4.0. Split because the whole book is ~1.95M chars.
- wikibooks_java_programming.txt — Java Programming (Wikibooks), Wikibooks contributors, main page + all subpages, 168 sections, 583,169 chars, sha256 69194b0499ff59134a0031999d213b496954f6ee531d586b99406b711f4161d2. Licence CC BY-SA 4.0 (dual GFDL, unversioned, no invariant sections), verified from Wikibooks:License. Assembled from the official enwikibooks dump (2026-11-05).
- openjdk_java_lang.txt — OpenJDK java.lang (curated), openjdk/jdk, master, commit 9d7642fc (2026-11-05), Object, String, AbstractStringBuilder, StringBuilder, Integer, Boolean, Enum + 9 core interfaces, 15 files, 508,414 chars, sha256 cd4fdf548429268244ad1c633a886e1a6429db518021bac952a5e01cca0f0763. Licence GPL-2.0-only with "CLASSPATH" Exception, verified from the repo LICENSE; each selected file's header carries the exception designation.
- openjdk_java_util.txt — OpenJDK java.util (curated), same repo/commit, ArrayList, HashMap, LinkedList, ArrayDeque, HashSet, List/Map/Set/Collection/Iterator, AbstractList/Map/Collection, Objects, Optional, 15 files, 630,857 chars, sha256 6fdb7f24071a32db2560731e529b6649518cd291dd91b66741cfd830c4ea0350. Licence GPL-2.0-only with "CLASSPATH" Exception.
- open_data_structures_java_code.txt — Open Data Structures, Java implementation code, patmorin/ods, master, commit 9d22c449 (2019-12-08), all 50 files under java/ods/, 194,101 chars, sha256 9f12072e5582a97714c3a78a29c9ca76a7ddd92ef8a941edb1900d996bd3bc5d. Licence CC BY 2.5 Canada, verified from the repo COPYING file. Book text (latex/) not assembled; java/test/acc and java/test/jdk excluded (Sun/Apache code, not ODS's own).
- apache_commons_lang.txt — Apache Commons Lang (curated), apache/commons-lang, master, commit e547d704 (2026-11-03), 13 utility files, 527,748 chars, sha256 52b7d6ce40feb8c4015b57d863b2e22501cfe6ba8a99b14b096e35c434dc6b7d. Licence Apache License 2.0, verified from the repo LICENSE.txt. StringUtils and ArrayUtils left out for size (mostly repetitive generated overloads).
- Excluded Java sources: Oracle's official Java tutorials/docs (not openly licensed); commercial books (Core Java, Effective Java, Head First Java, etc.); "Programming with Java" / "Java with BlueJ" (Open Textbook Library, licences unconfirmed, not assembled).

## Mojo, added 2026-11-05 (assembled locally, not yet pushed)
- mojo_manual.txt — Mojo Manual and Language Reference (official Modular documentation), modular/modular, main, HEAD 03501ff8 (2026-11-05), Mojo/docs/site/manual + reference + top-level docs pages, 85 sections, 1,019,141 chars, sha256 524c315bd4204bf4ca10bb9748f19f1914f3ced83ae4f5f26bf978a410129a57. Licence Apache License v2.0 with LLVM Exceptions, verified from the repo LICENSE and README. Mojo went fully open source on 2026-08-18 (Mojo 1.0); the MAX stack in the same monorepo is under the MAX License and was NOT included.
- mojo_stdlib_core.txt — Mojo Standard Library, Core (builtin + collections + prelude), same repo/commit, 34 files, 1,066,016 chars, sha256 3c762b20959ab1a31ddca64443ee3b30d38b97580580fab8e5fc2247676a2602. Licence Apache 2.0 with LLVM Exceptions.
- mojo_stdlib_systems.txt — Mojo Standard Library, Systems (math, memory, algorithm, SIMD, traits, iter, utils, os/sys, time, random, hash, complex), same repo/commit, 70 files, 1,173,773 chars, sha256 bd9a0d20204e6f2f0279465d9deec52c163e83a62ed6a25da63de31f913f0ca2. Licence Apache 2.0 with LLVM Exceptions. Remaining modules (atomic, base64, benchmark, bit, compile, ffi, format, io, logger, net, pathlib, python, reflection, runtime, stat, subprocess, tempfile, testing, _gpu, _plugin) left out for the ~1.2M budget.
- mojo_examples.txt — Mojo Official Examples, same repo/commit, Mojo/examples, 31 files, 74,520 chars, sha256 d3328ba7ba0f59ce907b0c30c77607bb5a1eb726e115922d4682409551de1f30. Licence Apache 2.0 with LLVM Exceptions.
- mojo_dojo.txt — Mojo Dojo learning materials, tictaqqn/mojodojo.dev, HEAD 258ab31 (2023-08-23), 40 .md files, 141,763 chars, sha256 d50488d67f53a1c77d15a22e4ef67d3085dd828b457626c2b19a0f1fcebea10f. Licence MIT. Pre-1.0 and stale: APIs taught (e.g. DynamicVector) have since been renamed/removed; the official Manual/stdlib should be weighted over it.
- mojo_learning.txt — mojo-learning tutorials, rd4com/mojo-learning, HEAD 927ad41 (2024-07-04), 36 files, 155,212 chars, sha256 efb7fc12059e352c642b08a85a3e9f897bcae081cf089ddbde488bca5117d772. Licence MIT. Same pre-1.0 staleness caveat as the Dojo.
- mojo_gym.txt — Mojo Gym exercises, VMois/mojo-gym, HEAD 64a1f94 (2024-02-10), 25 files, 14,447 chars, sha256 41c4bc33ab876728faa7a99c5c59720939d86eda7c1e951c7c72df03f0ae1a73. Licence MIT. Same pre-1.0 staleness caveat.
- Excluded Mojo sources: Mojo Miji (CC BY-NC-ND 4.0), "Mojo By Example" / ruhati.net (CC BY-ND 4.0), seanpm2001/Learn-Mojo (licence unclear), commercial Mojo books.

## Julia, added 2026-11-05 (assembled locally, not yet pushed)
- julia_manual_part1.txt — Julia Documentation: The Julia Manual (part 1), JuliaLang/julia, master, commit ac394d3c, doc/src/index.md + doc/src/manual/ first half (alphabetical, split at halfway point), 23 sections, 593,093 chars, sha256 8983cc8368f4c98a5bbb52f33ffb7dbfaa88535a0753169a293405b4320591bd. Licence MIT, verified from the repo LICENSE.md (its text expressly covers "this software and associated documentation files").
- julia_manual_part2.txt — Julia Manual (part 2), same repo/commit, second half, 21 sections, 594,321 chars, sha256 dc1e39caa127462c4dfdcfc74be292a97a7fcf0215d50129673e47d042303a3e. Licence MIT.
- julia_base_source.txt — Julia Base Library Source (curated), same repo/commit, base/ (types, numbers, arrays, dicts/sets, iterators, sort/reduce…), 37 files, 1,101,233 chars, sha256 489c2cec185285c977bcda62732f432413f847b957d68f507903de4109fb8f1f. Licence MIT.
- julia_base_source2.txt — Julia Base Library Source (part 2), same repo/commit, the 16 curated base files that missed the cap in part 1, 461,753 chars, sha256 1c31f3a2610ed0c17fbda7ef8b6dd3e84b89d89b51bbc01b66065a1f76f792d2. Licence MIT. Together parts 1+2 are the complete 53-file curated list.
- julia_stdlib_source.txt — Julia Standard Library Source (part 1), same repo/commit, stdlib src (Dates, Random, Test, InteractiveUtils, Profile, Serialization, Sockets, FileWatching, Printf, Artifacts, Mmap, SharedArrays, Base64, Unicode, TOML, UUIDs, CRC32c, Future, Libdl, Logging), 57 files, 1,017,134 chars, sha256 3176fa4514ef9c3adcdb2a9687af8c8940f7e3a43716ee1bf716e0444ea7026b. Licence MIT.
- julia_stdlib_source2.txt — Julia Standard Library Source (Markdown, REPL, LibGit2), same repo/commit, 53 files, 766,924 chars, sha256 9b62878558bb6a448b68c0a8b65d22a2f0b35c82491c8899846a108a8d2dba65. Licence MIT. LinearAlgebra, Statistics, SparseArrays, Pkg, Distributed, Downloads, DelimitedFiles were not present in the sparse checkout (only .version stubs) and are absent — follow-up with a full clone.
- think_julia.txt — Think Julia: How to Think Like a Computer Scientist, Ben Lauwens, BenLauwens/ThinkJulia.jl, master, commit c5c5d5a7, all 29 AsciiDoc book files + book.asciidoc, 30 sections, 464,265 chars, sha256 3a8f23f96ee48e0378d21b9539d9172c0a5e9e2ddc17a3b695b0dd4e7be99ebb. Licence CC BY-NC 3.0 Unported, verified from the repo LICENSE.md.
- julia_data_science.txt — Julia Data Science, JuliaDataScience/JuliaDataScience, main, commit 0ca61f44, all 42 contents/*.md files, 291,598 chars, sha256 0dba3bfde7de0572e17f32246057736982f50a98a4302698b3281c428e0281d7. Licence CC BY-NC-SA 4.0 International, verified from the repo LICENSE + README. Repo is archived by its authors; book still published.
- julia_by_example.txt — Julia by Example, samuelcolvin/JuliaByExample, master, commit 9fc5516b, README + main_page + all src/*.jl examples, 18 sections, 34,765 chars, sha256 da1d4366695c955a0a4a63b2c040468325cc07fc97c832c385877d9a63074087. Licence MIT.
- enccs_julia_intro.txt — Introduction to Programming in Julia (ENCCS lesson), ENCCS/julia-intro, main, commit 0a6d6a34, README + all content/*.rst lesson files, 10 sections, 92,013 chars, sha256 34680ee663875d36f2c6902cac774939c6993b1ffbf5ab35409be83e6985b3e0. Licence CC BY 4.0 International (lesson text; code MIT per LICENSE.code).
- Excluded Julia sources: Geospatial Data Science with Julia (CC BY-NC-ND 4.0); QuantEcon "Quantitative Economics with Julia" (no LICENSE in the repo, unverified); Wikibooks "Introducing Julia" (no licence statement verifiable from the wikibook's own page — follow-up via MediaWiki API once confirmed).

## Erlang, added 2026-11-05 (assembled locally, not yet pushed)
- erlang_handbook.txt — Erlang Handbook, esl/erlang-handbook, master, all 12 English chapters, 63,813 chars, sha256 c664d8773328c286a60f98f4e442627bd2731ac09b19913587473c428ae8fabc. Licence CC BY-SA 3.0, verified from the repo. LaTeX stripped minimally; footnotes dropped.
- erlang_in_anger.txt — Stuff Goes Bad: Erlang in Anger, Fred Hébert, heroku/erlang-in-anger, master, copyright notice + intro + chapters 101-109 + conclusion + the book's 7 code files, 19 sections, 148,566 chars, sha256 d5b87c71000fb9b98d135ca52105fa4a7a35a1b951de1cd5f84f9065463aaa6c. Licence CC BY-NC-SA 4.0.
- adopting_erlang.txt — Adopting Erlang, adoptingerlang/adoptingerlang, main, the whole book as its single adoptingerlang.org source file, 357,390 chars, sha256 195d258ac22a04e5e6d27c130adbd5933307f2e1c428f97a193c7f1f863577d4. Licence CC BY-NC-SA 4.0. Caveat: the .org header names Fred Hébert + Tristan Sloughter while the booksite credits Evan Vigil-McClanahan as third co-author (all three listed in provenance).
- beam_book.txt — The BEAM Book: Understanding the Erlang Runtime System, 1st open edition (2025), happi/theBeamBook, main, 25 chapters in book.asciidoc order + references + code-listings appendix, 70 sections, 674,292 chars, sha256 8da39f9ecef36e442f20f9e2a80ab30a00a7d6258dbe38a727e5038ed5455b2a. Licence CC BY 4.0.
- erlang_otp_docs.txt — Erlang/OTP Documentation (getting started, tutorial, reference manual, programming examples, 6 stdlib module docs), erlang/otp, master, 64 sections, 774,731 chars, sha256 220956cd1e3d0950575468f6ed128dfa278f72a844a75ef7c385b5fd10608fb4. Licence Apache License 2.0, verified from the repo LICENSE.
- erlang_otp_design.txt — Erlang/OTP Documentation (design principles incl. gen_server/supervisor/release/appup/secure coding, efficiency guide, system principles), same repo, 32 sections, 502,109 chars, sha256 57864b78e7e409e5f874c683df7988d6a445f1e838df8266d29fd0e746df8375. Licence Apache License 2.0.
- erlang_otp_stdlib.txt — Erlang/OTP stdlib source (curated), same repo, lib/stdlib/src/ unmodified (gen_server, gen_statem, supervisor, gen_event, lists, string, ets, maps, queue, sets, gb_trees, io_lib), 12 files, 1,064,550 chars, sha256 96d9dacef06984df846705b3e9aa01361627e92e45f64622724ef2ecb146ad12. Licence Apache License 2.0.
- erlang_otp_kernel.txt — Erlang/OTP kernel source (curated), same repo, lib/kernel/src/ unmodified (application, code, file, logger, os, rpc, global, net_kernel, gen_tcp, gen_udp, error_logger, inet_db, dist_util, auth, kernel, erl_boot_server), 16 files, 876,472 chars, sha256 93aacef0690209dc06b5e5b90da0f9a0524e564206cfc1a855acf43a687a54f0. Licence Apache License 2.0.
- Excluded Erlang sources: Learn You Some Erlang for Great Good! (CC BY-NC-ND 3.0 — the biggest Erlang teaching text, main gap); Études for Erlang (CC BY-NC-ND 3.0); commercial books (Programming Erlang, Erlang Programming, Erlang and OTP in Action, Designing for Scalability); Joe Armstrong's thesis / Concurrent Programming in Erlang (copyrighted, no open licence).

## Elixir, added 2026-11-05 (assembled locally, not yet pushed)
- elixir_stdlib_core.txt — Elixir Standard Library Core (curated), elixir-lang/elixir, main, commit cb869525 (2026-11-04), Kernel, Enum, String, Macro, Code, Module, Exception, File, Access, List, Keyword, 11 files, 1,025,415 chars, sha256 0b8f8a556a0e1d6e2f9bd51e13dd742d2d64179f2c2b131933a3370b2741c7c5. Licence Apache License 2.0, verified from the repo LICENSE.
- elixir_otp_core.txt — Elixir OTP / Concurrency Core (curated), same repo/commit, GenServer, Supervisor, DynamicSupervisor, Application, Task, Task.Supervisor, Registry, Agent, Stream, System, Process, 11 files, 472,389 chars, sha256 3db5bf44f523aeb77f60b39bc68a49e1b4ef48cc53c7825ab233cdb8dc7df663. Licence Apache License 2.0.
- elixir_guides.txt — Elixir Official Guides (Getting Started, Mix & OTP, meta-programming, anti-patterns, references, cheatsheets), same repo/commit, lib/elixir/pages/, 51 sections, 549,166 chars, sha256 3509c043f61dd53f257998084006325566af2e3b4727cd9d9127eb291c405a40. Licence Apache License 2.0. (elixir-lang.org now redirects the guides to hexdocs.pm/elixir; text taken from the repo itself.)
- elixir_school.txt — Elixir School Lessons (English), elixirschool/elixirschool, main, commit 4e5bea24 (2026-09-04), all 49 English lessons, 403,789 chars, sha256 b1b6ca109fbe9d8429b918ffe6bfe0e1ac2bd350129eccc9e3865b93d7a585de. Licence Apache License 2.0, verified from the repo LICENSE (the old README's MIT badge is stale).
- joy_of_elixir.txt — Joy of Elixir, radar/joyofelixir, master, commit 3755bed5 (2024-03-25), full book from _includes/ch/, 24 sections, 372,593 chars, sha256 25a619574ba3c06b350a6c746443b019b3f67d76e5956a204fba652fe4f20064. Licence CC BY-SA 4.0, verified from the book's own About page and license.txt in the repo.
- thirty_days_of_elixir.txt — 30 Days of Elixir, seven1m/30-days-of-elixir, master, commit 88503ac0 (2022-04-13), README + all 30 .exs exercises, 31 sections, 90,953 chars, sha256 9b65abc276f068c3bac877527b405783866bad9bb70c1d4c51ecc6d58bb42c62. Licence MIT.
- elixir_style_guide.txt — The Elixir Style Guide, christopheradams/elixir_style_guide, master, commit 1f2fdf68 (2024-05-06), README.md only, 33,519 chars, sha256 4de7a04080a913e6bcb3f0ecc8ebf7d5ea1be550651076a5ea089f1c5888b24b. Licence CC BY 3.0 Unported, from the README's own "Copying / License" section (no LICENSE file).
- elixir_learning_materials.txt — Elixir Learning Materials (UCLL courses: basics, OTP, distributed), fergal-whyte/elixir-learning-materials, main, commit 5d3ab53c (2022-02-16), all .md/.exs/.ex + README, 424 sections, 465,214 chars, sha256 da6906969662434fcb02fb767f39ed01d83b68021f4a2f812d4b938dbef4435c. Licence CC BY-NC-SA 4.0, verified from the repo LICENSE.
- phoenix_guides.txt — Phoenix Framework Guides (official), phoenixframework/phoenix, main, commit 6daf29b3 (2026-11-02), all 43 guides/*.md, 499,004 chars, sha256 c885d93484c4f93574c2c1be56f04c190b9ead23390fe77a3001905ee40e33c6. Licence MIT, verified from the repo LICENSE.md.
- phoenix_source.txt — Phoenix Framework Source (curated), same repo/commit, lib/phoenix/ core (Router, Endpoint, Controller, Channel, Socket, Presence, VerifiedRoutes, Token, Logger, etc.), 25 files, 403,889 chars, sha256 1e0cdb8eead65ba2866cea1e1ac83605d8060a3b63e714fe4ce9957cd729f39d. Licence MIT.
- taxfix_elixir_course.txt — Elixir Course (Taxfix), taxfix/elixir-course, main, commit fc061ca4 (2026-08-04), README.md (the repo's entire text), 20,403 chars, sha256 29e290846bbfef575ad170d61bd9489f75a99b63ac1bd6333c3adaf4bcfc553a. Licence CC BY-NC-SA 4.0, from the README's own licence statement.
- Excluded Elixir sources: Elixir in Action, Programming Elixir, The Little Elixir & OTP Guidebook, Elixir Cookbook (commercial); Études for Elixir (© O'Reilly, no free licence); Elixir Succinctly (all rights reserved); The Ultimate Guide to Elixir for Object-Oriented Programmers (no licence statement, Kindle edition sold).

## Solidity, added 2026-11-05 (assembled locally, not yet pushed)
- solidity_docs.txt — Solidity Documentation (official), ethereum/solidity, master, commit d2acac1a (2026-11-04), all 69 .rst under docs/, 990,186 chars, sha256 7882ea0ed683737e08a51e3fcee869c46a33c27feb3e28fbb2499fcd6618f1a8. Licence GPL-3.0, verified from the repo LICENSE.txt. Note: the expected CC BY 4.0 for the docs text did NOT verify — the CC BY 4.0 statement found applies to the Solidity logo only; the docs are recorded under the repo-wide GPL-3.0.
- solidity_compiler_source.txt — Solidity Compiler Source (curated core pipeline), same repo/commit, libsolidity/ (Parser, AST/Types, TypeChecker, CompilerStack/StandardCompiler, ContractCompiler/CompilerUtils), 14 files, 729,806 chars, sha256 598328b082a153b3e61a17b7e30eab900f5f9f0c13b57dacb767aa8aa49f0499. Licence GPL-3.0.
- openzeppelin_contracts_core.txt — OpenZeppelin Contracts (core: token ERC20/721/1155/6909, access, governance, finance, proxy, metatx, account, crosschain, interfaces, vendor/compound), OpenZeppelin/openzeppelin-contracts, commit efaa6f78 (2026-11-02), 174 files, 837,998 chars, sha256 41d4b74d7c055586d2ec7057392098e607cac84e65b989d9fa0357129a22b7d6. Licence MIT. contracts/mocks/ excluded (126 test-mock contracts).
- openzeppelin_contracts_utils.txt — OpenZeppelin Contracts (utils), same repo/commit, all of contracts/utils/ (cryptography, math, structs, ERC165, etc.), 76 files, 781,460 chars, sha256 194b86912f1f424f9938f54b7540a359685f0d4f079806359ffdfc9b836b4644. Licence MIT.
- solidity_by_example.txt — Solidity by Example (Cyfrin), Cyfrin/solidity-by-example.github.io, gh-pages, commit 5bcdca02 (2026-01-20), 129 .md + 179 .sol (basics, apps, DeFi, hacks, EVM/assembly, Foundry), 308 sections, 481,073 chars, sha256 4cd6e8b4cb750ba27c23788a990487da5814865c9da9a59d16066b98cc613773. Licence MIT.
- cryptozombies_lesson_code.txt — CryptoZombies Lesson Code, CryptozombiesHQ/cryptozombies-lesson-code, commit 48780337 (2019-11-27), Lesson 1 only, 12 non-empty .sol files, 4,734 chars, sha256 c529f4800ee7616b05ee6a9bdd9f40794e4613f9c6fb9457b878c9d528113982. Licence GPL-3.0. Lessons 2-6 .sol files are all 0 bytes, lessons 7-9 were removed, lessons 10-11 have no .sol — recorded in provenance.
- solidity_examples_official.txt — Solidity Examples (official ethereum/solidity-examples), commit ba15d56b (2022-09-07), 32 .sol (bits/bytes/math/patricia-tree/strings libs + examples/tests/perf), 169,686 chars, sha256 7dbd2e0ed6e8a1ef3dde861fee90f76d109dbab4a8bc4a70c6c132e6d10321ad. Licence MIT.
- wtf_solidity.txt — WTF Solidity Tutorial (English), AmazingAng/WTF-Solidity, commit dd722e66 (2026-10-11), Languages/en/: 57 lessons + 16 security topics (S01-S16; S17 has no English translation) + English index README, 179 sections, 882,288 chars, sha256 95f448f0acb3119c990bcd433d959cb54dc62fe3560b7f3f513ab065f140eed9. Licence prose CC BY-NC-SA 4.0, code MIT, both from the repo LICENSE.
- Excluded Solidity sources: Mastering Ethereum (CC BY-NC-ND 4.0); raineorshine/solidity-by-example (no LICENSE); CryptozombiesHQ/cryptozombie-lessons (all rights reserved, Loom Network); ConsenSys smart-contract-best-practices (no LICENSE).
- Coordinator note 2026-11-05: the six Solidity provenance .json files originally recorded byte counts in their "chars" fields; corrected to decoded character counts (the assembler's counting) with SHA-256 unchanged — see the notes in each .json.

## Not yet added
- Python: the project's own language, and the core
  language alongside Rust. No Python tutorial/code
  source has been added to this corpus yet; the
  project's own Python code (mini_ai/, train_gpt.py)
  is original to this project and is a candidate
  source, but it has not been assembled into a training
  file yet.
