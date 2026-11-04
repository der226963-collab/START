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
  approval in the START chat:
  think_data_structures_downey.txt — Allen B. Downey,
  Think Data Structures v1.1.0, Green Tea Press, 191 pages,
  extracted from user-uploaded PDF with pdftotext, cleaned
  (form feeds removed, hyphenated line breaks joined),
  237,179 chars, sha256 710c58e1…. Licence verified from
  the PDF copyright page itself: CC BY-NC-SA 3.0 Unported.
  This is the Green Tea Press version, NOT the O'Reilly
  all-rights-reserved edition. Assembled corpus with this
  file: 2,160,794 chars from 4 files.
