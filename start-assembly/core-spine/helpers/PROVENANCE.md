# Provenance — borrowed helpers

Date: 2026-11-11. Local only; nothing pushed to GitHub. Copied on Eric's
direction ("Copy the three small helpers next", 2026-11-11), from the
audit clones in `../source-audit/` — the clones were not modified.

## What was copied (3 helpers, 2 projects, Apache-2.0)

| Helper in `borrowed_helpers.py` | Source repo | Source file | Lines | Clone commit | Licence |
|---|---|---|---|---|---|
| `chunk_by_word`, `is_real_paragraph_end` (+ `SENTENCE_ENDINGS`, `PARAGRAPH_ENDINGS`) | topoteretes/cognee | `cognee/tasks/chunks/chunk_by_word.py` | 87 (whole file) | 8853378eae5366addb064e758e560a456146ae1a (pyproject version 1.6.7) | Apache-2.0 |
| `chunk_content_hash`, `content_chunk_id` | topoteretes/cognee | `cognee/modules/chunking/chunk_id.py` | 22 (whole file) | same Cognee clone/commit as above | Apache-2.0 |
| `normalize_url` | unclecode/crawl4ai | `crawl4ai/utils.py` lines 2259–2358 | ~100 (one function only) | cae74b203a33994f7e13b9052c3b0d5c93daa0e6 (`crawl4ai/__version__.py` 0.9.5) | Apache-2.0 |

The full Apache-2.0 licence notice is kept at the top of each section in
`borrowed_helpers.py`. The source files themselves carry no copyright
header, so the notice names the project contributors and the repo.
Licences were verified from each repo's own LICENSE file in the clone
(batch 2 audit, `../source-audit/CEDAR_EGG_COGNEE_GRAPHITI_CRAWL4AI_AUDIT.md`).

## Changes made (extraction only)

- Nothing in the copied code was changed except extraction: the three
  pieces were placed in one module, their imports hoisted to the top of
  that module (`re`, `collections.abc`, `hashlib`, `uuid`, `urllib.parse`).
- Verified by diff: each copied body is byte-identical to the source
  (checked with a script after writing the module).
- `normalize_url` was extracted alone. The rest of `crawl4ai/utils.py`
  (3,786 lines; module-level imports bs4, lxml, httpx, numpy, requests,
  xxhash, litellm) was NOT copied.
- No other Cognee, Graphiti, Crawl4AI, Cedar, or egg code was copied in
  this step.

## Stdlib-only verification

- The module's imports were checked with `ast`: `re`, `collections`,
  `hashlib`, `urllib`, `uuid` — all in `sys.stdlib_module_names`.
- The module also imports cleanly under the system Python (no venv, no
  third-party packages on the path). No dependency was added.

## What these helpers are — and are not

- Text chunking (`chunk_by_word`, `chunk_id`) and URL canonicalisation
  (`normalize_url`) for untrusted input. They have no authority over
  plans, verification, governance, or any decision: they are not wired
  into any verify, governance, or decision path in this assembly.
- `chunk_id` is content-derived: an unchanged chunk keeps its id no
  matter where it sits, and re-ingesting identical content is
  idempotent; the occurrence counter disambiguates identical texts
  appearing more than once in the same document.

## Known findings (measured, not hidden)

1. **Crawl4AI's own test file does not match the function in this
   clone.** `crawl4ai/repo/tests/test_normalize_url.py` (20 cases)
   expects behaviour the cloned function (0.9.5) does not have:
   - It expects `normalize_url("", base)` to return the base URL; the
     function returns `None` for an empty/None href (its docstring says
     "or None if href is empty/None").
   - It expects fragments to be preserved by default; the function
     drops them unless `keep_fragment=True`.
   - It expects `ValueError("Invalid base URL format")` for an
     `ftp://` base and for a base with an empty netloc; the function
     never validates the base and returns a URL instead
     (`ftp://example.com/page.html`, `http:///path/page.html`).
   Checked case by case against the extracted function: 16 of the 20
   upstream cases pass as written; the 4 above do not. The test file
   was presumably written against a different revision of the
   function. Our tests in `../tests/test_borrowed_helpers.py` assert
   the copied function's ACTUAL behaviour (16 upstream cases verbatim,
   plus explicit cases for the 4 mismatches and the invalid-base
   behaviour), and this mismatch is recorded here rather than silently
   "fixing" the copied function to match the test file.
2. `chunk_by_word`'s `is_real_paragraph_end` returns True whenever the
   last character is a sentence ending, regardless of position (its
   first branch does not look at `current_pos`). Copied verbatim; the
   behaviour is tested, not fixed, in this step.
3. Cognee's `chunk_by_word` cannot be imported from the Cognee package
   directly in this environment — importing `cognee` pulls in its
   `__init__` which needs `dotenv` and the rest of the application.
   That coupling is exactly why the standalone file was copied instead.
