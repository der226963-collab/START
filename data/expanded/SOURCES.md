# Expanded corpus — sources, licences, and status (LOCAL ONLY, NOT YET PUSHED)

## Decision, 2026-11-04
Eric approved including NC (NonCommercial) material in the START
training expansion. That reverses the earlier draft rule that
excluded NC-SA text. NC material is included WITH its licence
terms recorded here, and those terms travel with the files:
- NC = non-commercial use only. Anyone reusing those files, or
  a derivative made from them, must not use them commercially.
- SA = share-alike. Adaptations must be shared under the same
  licence.
- BY = attribution to the original authors/publisher is required.
This does not change the guardrails, safety files, or approval
policy, and it does not make copyrighted (all-rights-reserved)
material acceptable. NC material is still openly licensed;
copyrighted textbooks with no open licence are still excluded.

## Licence groups in this expansion
1. Public domain (US) — Project Gutenberg science books, and
   US federal government (NASA/NOAA) material. No licence
   restriction, Gutenberg trademark/header removed only from
   the underlying public-domain text, not claimed as our own.
2. CC BY 4.0 / CC BY 2.5 CA — attribution only, commercial
   use allowed. Examples: philschatz Physics (per-book check
   pending), Pat Morin Open Data Structures (CC BY 2.5 CA).
3. CC BY-SA 4.0 / 3.0 — attribution + share-alike. Examples:
   venhance/napkin (text CC BY-SA 4.0), oscarlevin/discrete-book
   3rd edition (CC BY-SA 4.0), OpenIntro Statistics 4th edition
   (CC BY-SA 3.0), Wikipedia articles (CC BY-SA 4.0, if used).
4. CC BY-NC-SA 4.0 — attribution + non-commercial + share-alike.
   NOW INCLUDED, by Eric's 2026-11-04 decision. Examples:
   most current OpenStax books (Chemistry 2e, University
   Physics, Calculus, Biology 2e, etc.), oscarlevin/discrete-book
   4th edition. These files must keep their NC-SA notice, and
   any push that includes them must say so plainly in the
   commit message and in this file.

## Status
- Gutenberg browser download task (2:53-3:10 PM EST, 2026-11-04):
  FAILED for a tool reason, not a licence reason. Chrome
  renders text/plain inline, so the browser download tool
  cannot save .txt files, and Ctrl+S attempts produced
  nothing verifiable (no pg*.txt found under /home/hatch).
  All four titles were confirmed public domain in the US.
  Per-book: Origin #1228 and Beagle #944 had verified
  plain-text links but could not be browser-downloaded;
  Euclid Heath translation is NOT on Gutenberg (no
  substitute made); Lyell #33224 (2.5 MB) also hung the
  browser tab.
- Gutenberg via the new fetcher (same day, after the browser
  failure): SUCCEEDED for two books, staged, NOT yet approved:
  pg1228.txt — Origin, First Edition 1859, 949,182 chars,
  sha256 dd09b437…; pg944.txt — Voyage of the Beagle,
  1,207,533 chars, sha256 660edbaf…. Plus earlier fetcher
  trial: 2009-0.txt — Origin, Sixth Edition, 1,257,091 chars.
  Lyell #33224 was not fetched by the fetcher yet: at
  2.5 MB it exceeds the fetcher's 2,000,000-char cap and
  would be refused, not truncated.
- OpenStax NC-SA PDF downloads: browser task started after
  Eric's NC approval, no files landed yet.
- GitHub textbook candidates (Napkin, Discrete, OpenIntro,
  ODS, Physics): surveyed and licence-checked, not yet
  downloaded or extracted (LaTeX/PreTeXt source needs a
  text-extraction step).
- APPROVED by Eric, 2026-11-04, and pushed (see commit in
  push record): 2009-0.txt — Origin, Sixth Edition,
  1,257,091 chars, public domain, sha256 7bd26f06…;
  Climate_change.txt — Wikipedia Climate change, 477,943
  chars, CC BY-SA 4.0, sha256 6269cc8f…. Assembled as
  data/expanded_corpus.txt: 1,735,034 chars from 2 files.
  Note, recorded honestly: the Wikipedia file still contains
  navigation/menu text from HTML stripping; Eric approved
  it knowing that.
- Still staged, NOT approved or pushed in that batch:
  pg1228.txt (Origin, First Edition, 949,182 chars) and
  pg944.txt (Voyage of the Beagle, 1,207,533 chars), both
  public domain, fetched via the fetcher after the browser
  Gutenberg task failed.
- APPROVED by Eric, 2026-11-04, second live fetcher test,
  and pushed: Renewable_energy.txt — Wikipedia Renewable
  energy, 188,581 chars, CC BY-SA 4.0, sha256 29674739….
  Assembled corpus updated to 1,923,615 chars from 3 files
  (Origin Sixth Edition, Climate change, Renewable energy).
  Same Wikipedia navigation-text caveat as Climate change;
  approved knowing that.
- MANUAL, user-provided, 2026-11-04, pushed by Eric's
  approval in the START chat, commit bd460f652d7762f90506680022ef0b0c3898459b:
  think_data_structures_downey.txt — Allen B. Downey,
  Think Data Structures v1.1.0, Green Tea Press, 191 pages,
  extracted from user-uploaded PDF with pdftotext, cleaned
  (form feeds removed, hyphenated line breaks joined),
  237,179 chars, sha256 710c58e1…. Licence verified from
  the PDF copyright page itself: CC BY-NC-SA 3.0 Unported.
  This is the Green Tea Press version, NOT the O'Reilly
  all-rights-reserved edition. Assembled corpus with this
  file: 2,160,794 chars from 4 files.
- MANUAL, user-provided, 2026-11-04, pushed by Eric's
  approval in the START chat:
  engineering_statics_baker_haynes.txt — Daniel W. Baker
  and William Haynes, Engineering Statics: Open and
  Interactive, Sept 26 2026 edition, 421 pages, extracted
  from user-uploaded PDF with pdftotext, cleaned
  (form feeds removed, hyphenated line breaks joined),
  589,865 chars, sha256 1208e16a…. Licence verified
  from the PDF About this Book page: CC BY-NC-SA 4.0
  International (GeoGebra content CC BY-NC-SA 3.0).
  Caveats: PDF pages 1, 315-317 are pictures, not text,
  and some font encodings are broken, so some extracted
  text may be garbled. Assembled corpus with this file:
  2,750,659 chars from 5 files.
- MANUAL, extracted from OpenStax PDFs, 2026-11-04,
  pushed by Eric's approval in the START chat as corpus PARTS (see below), after a single-file push failed: 8 OpenStax books, all licence-checked
  from each PDF's front matter as CC BY-NC-SA 4.0:
  openstax_university_physics_vol1.txt 2,107,391 chars
  sha256 c37e7648e7fe…; vol2 1,694,863 chars d14b7ed08bbd…;
  vol3 1,346,026 chars 5f5705cf0b184…;
  openstax_chemistry_2e.txt 2,496,355 chars 57aca968a2fa…;
  openstax_biology_2e.txt 4,000,319 chars 78f9629da3c3…;
  openstax_calculus_vol1.txt 980,199 chars d689e1219a75…;
  vol2 903,856 chars f976f8113c82…; vol3 1,152,439 chars
  e41694ed64d7…. OpenStax total 14,681,448 chars.
  Assembled corpus with these files: 17,432,107 chars
  from 13 files.

- MANUAL, user-provided, 2026-11-04, NOT yet pushed:
  health_wellness_fitness_alsup.txt — Jessica Alsup,
  The Basics of Health, Wellness, and Fitness [Revised
  Edition], 2025, ROTEL Project, 243 pages, extracted
  from user-uploaded PDF with pdftotext, cleaned
  (form feeds removed, hyphenated line breaks joined),
  213,588 chars, sha256 61791b6b0fb4…. Licence verified
  from the PDF title page: CC BY-NC-SA 4.0 International,
  except where otherwise noted.

- CORPUS SPLIT, 2026-11-04: data/expanded_corpus.txt
  (17,518,241 bytes, 17,432,107 chars, 13 files) is too
  large for a single push (limit 2,023,884 bytes), so it
  is pushed as data/expanded_corpus_parts/part-01..13.txt
  (max 1,400,000 bytes each, split at line boundaries; first
  attempt at 1,900,000 bytes/part was refused; the limit
  turned out to be a TOTAL push payload of about 16.8 MB,
  not a per-file limit, so the 13 parts are pushed in
  two commits: parts 01-08, then parts 09-13),
  generated by tools/split_expanded.py, with README.md
  and manifest.json in that folder. Reassemble with:
  cat data/expanded_corpus_parts/part-*.txt >
  data/expanded_corpus.txt. Local training still uses
  the unsplit data/expanded_corpus.txt. The individual
  OpenStax .txt files over the limit are NOT pushed
  individually; their full text is in the corpus parts.

- STAGED FILES PUSHED, 2026-11-04, by Eric's approval:
  pg1228.txt (Origin First Edition 1859, staged 949,182
  chars sha256 dd09b437…, assembled cleaned 932,991 chars
  after Gutenberg markers stripped) and pg944.txt
  (Voyage of the Beagle, staged 1,207,533 chars sha256
  660edbaf…, assembled cleaned 1,188,563 chars), both
  public domain (US), approved via the fetcher.
  Assembled corpus with these files: 19,553,661 chars
  from 15 files, 19,641,351 bytes, split into 15 parts
  (max 1,400,000 bytes each) by tools/split_expanded.py.
  The Health book was held out of this assembly/push
  (not yet approved for push) and is local only.
- CORPUS SPLIT UPDATE, 2026-11-04: parts are now
  part-01..15.txt (previously 01..13), reflecting the
  two Gutenberg books added above. Reassembly SHA for
  this corpus: be0ac7aa5d89e1a73e1304d831ca17a53d4db5b69be5078828ba246210e9b950.

- MANUAL, user-provided, 2026-11-04, pushed by Eric's
  approval in the START chat (single word 'Approved'
  after the Gutenberg push report, taken as approval
  for the Health book, the only book then outstanding):
  health_wellness_fitness_alsup.txt — Jessica Alsup,
  The Basics of Health, Wellness, and Fitness [Revised
  Edition], 213,588 chars, sha256 61791b6b0fb4…,
  CC BY-NC-SA 4.0 International. Assembled corpus with
  this file: see split manifest for the new total.

- PROGRAMMING LANGUAGES, 2026-11-04, LOCAL ONLY, NOT
  YET PUSHED: rust_book.txt — The Rust Programming
  Language, Steve Klabnik, Carol Nichols, and Chris
  Krycho, with contributions from the Rust Community,
  assembled from rust-lang/book, branch main, 111
  chapter .md files in SUMMARY.md order, minimal
  cleaning only (mdBook directives / HTML comments
  stripped, code blocks and prose intact), 1,119,540
  chars, sha256 d33ef85f6ef53c88e4521c0d04508ef8480
  c8c06013b09f94351f71368dd5e81, provenance in
  rust_book.txt.json (status proposed, approved false,
  pushed false at assembly). Licence verified from
  that repo's LICENSE-MIT: MIT, Copyright (c) 2010
  The Rust Project Developers; Rust project is dual
  MIT / Apache 2.0. This is the first programming-
  language source, under Eric's 2026-11-04 decision
  that programming languages are in scope because the
  model needs to self-write code to improve itself,
  with self-edit guardrails unchanged. Core languages
  are Python (the project's own language) and Rust;
  C and Java are the next wave Eric flagged as having
  potential, with no C or Java source verified or
  added yet. Rust assembled into data/expanded_corpus.txt
  2026-11-04: corpus now 20,886,788 chars from 17 files,
  sha256 295fae7a43ce8a237bad5af0b5fef92a41317a9167ac
  92c49d23a714da31cb38. Medium test passed first
  (20 steps, val 4.2860, pre-Rust corpus); a medium
  Rust-inclusive training run was started in the
  background after the push, generation check pending.
