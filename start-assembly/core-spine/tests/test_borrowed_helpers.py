"""Tests for the borrowed helpers (helpers/borrowed_helpers.py).

Copied code from Cognee (chunk_by_word, chunk_id) and Crawl4AI
(normalize_url), Apache-2.0, stdlib-only. Run from core-spine/ with:
    .venv/bin/python -m unittest discover -s tests -v

For normalize_url, 16 cases are taken verbatim from Crawl4AI's own
test file (tests/test_normalize_url.py in the audit clone). Four of its
cases do NOT match the function in the cloned version (0.9.5) and are
tested here against the function's ACTUAL behaviour instead — see
helpers/PROVENANCE.md finding 1: empty href returns None (not the base
URL), fragments are dropped by default, and invalid base URLs do not
raise (the function never validates the base).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from helpers.borrowed_helpers import (  # noqa: E402
    chunk_by_word,
    chunk_content_hash,
    content_chunk_id,
    is_real_paragraph_end,
    normalize_url,
)


class TestChunkByWord(unittest.TestCase):
    SAMPLE = "Hello world. This is a test.\n\nNew paragraph here. And more text!"

    def test_join_recreates_input(self):
        chunks = list(chunk_by_word(self.SAMPLE))
        self.assertEqual("".join(t for t, _ in chunks), self.SAMPLE)

    def test_sentence_and_paragraph_labels(self):
        labels = [label for _, label in chunk_by_word(self.SAMPLE)]
        self.assertIn("sentence_end", labels)
        # "test." is followed by a blank line -> paragraph_end
        self.assertIn("paragraph_end", labels)
        self.assertIn("word", labels)

    def test_sentence_end_chunk_keeps_trailing_space(self):
        chunks = list(chunk_by_word("Hello world. Next."))
        self.assertIn(("world. ", "sentence_end"), chunks)

    def test_empty_input_yields_nothing(self):
        self.assertEqual(list(chunk_by_word("")), [])

    def test_long_input_splits_and_rejoins(self):
        long_text = " ".join(f"word{i}." for i in range(100))
        chunks = list(chunk_by_word(long_text))
        self.assertGreater(len(chunks), 50)
        self.assertEqual("".join(t for t, _ in chunks), long_text)

    def test_single_word_no_ending(self):
        self.assertEqual(list(chunk_by_word("hello")), [("hello", "word")])

    def test_is_real_paragraph_end_after_sentence(self):
        self.assertTrue(is_real_paragraph_end(".", 11, self.SAMPLE))

    def test_is_real_paragraph_end_false_mid_text(self):
        # "w" is not a sentence ending and the next non-space char is
        # lowercase, so this is not a paragraph end.
        self.assertFalse(is_real_paragraph_end("w", 1, self.SAMPLE))


class TestChunkId(unittest.TestCase):
    def test_same_text_same_hash(self):
        self.assertEqual(
            chunk_content_hash("same text"), chunk_content_hash("same text"))

    def test_different_text_different_hash(self):
        self.assertNotEqual(
            chunk_content_hash("text one"), chunk_content_hash("text two"))

    def test_same_args_same_id(self):
        h = chunk_content_hash("chunk text")
        self.assertEqual(
            content_chunk_id("doc-1", h, 0),
            content_chunk_id("doc-1", h, 0))

    def test_occurrence_disambiguates_identical_text(self):
        h = chunk_content_hash("repeated paragraph")
        self.assertNotEqual(
            content_chunk_id("doc-1", h, 0),
            content_chunk_id("doc-1", h, 1))

    def test_different_document_different_id(self):
        h = chunk_content_hash("chunk text")
        self.assertNotEqual(
            content_chunk_id("doc-1", h, 0),
            content_chunk_id("doc-2", h, 0))

    def test_id_does_not_depend_on_position(self):
        # Position is not an input to the id at all: the same text in two
        # different documents/positions, same document id and occurrence,
        # gives the same id. (An edit that shifts positions therefore
        # does not change the id — the point of content-derived ids.)
        h = chunk_content_hash("unchanged chunk")
        id_early = content_chunk_id("doc-1", h, 0)
        id_after_edit_elsewhere = content_chunk_id("doc-1", h, 0)
        self.assertEqual(id_early, id_after_edit_elsewhere)

    def test_reingest_idempotent(self):
        h = chunk_content_hash("re-ingested chunk")
        first = content_chunk_id("doc-1", h, 2)
        second = content_chunk_id("doc-1", h, 2)
        self.assertEqual(first, second)


class TestNormalizeUrl(unittest.TestCase):
    # 16 cases verbatim from Crawl4AI's tests/test_normalize_url.py
    # (the 4 that do not match this clone's function are covered
    # separately below, against actual behaviour).
    UPSTREAM_CASES = [
        ("path/to/page.html", "http://example.com/base/",
         "http://example.com/base/path/to/page.html"),
        ("page.html", "http://example.com/base/",
         "http://example.com/base/page.html"),
        ("page.html", "http://example.com/base",
         "http://example.com/page.html"),
        ("http://another.com/page.html", "http://example.com/",
         "http://another.com/page.html"),
        ("  page.html  ", "http://example.com/",
         "http://example.com/page.html"),
        ("page.html?query=test", "http://example.com/",
         "http://example.com/page.html?query=test"),
        ("https://secure.example.com/page.html", "http://example.com/",
         "https://secure.example.com/page.html"),
        ("../otherpage.html", "http://example.com/base/current/",
         "http://example.com/base/otherpage.html"),
        ("/otherpage.html", "http://example.com/base/current/",
         "http://example.com/otherpage.html"),
        ("file.html", "http://example.com/path",
         "http://example.com/file.html"),
        ("page.html", "http://example.com",
         "http://example.com/page.html"),
        ("?query=true", "http://example.com/page.html",
         "http://example.com/page.html?query=true"),
        ("./P020241203375994691134.xlsx",
         "http://example.com/zwgk/fdzdgk/zdxx/spaq/t19360680.shtml",
         "http://example.com/zwgk/fdzdgk/zdxx/spaq/P020241203375994691134.xlsx"),
        ("another.doc",
         "http://example.com/zwgk/fdzdgk/zdxx/spaq/t19360680.shtml",
         "http://example.com/zwgk/fdzdgk/zdxx/spaq/another.doc"),
        ("path/file.html", "http://example.com:8080/base/",
         "http://example.com:8080/base/path/file.html"),
        ("path%20with%20spaces/file.html", "http://example.com/",
         "http://example.com/path%20with%20spaces/file.html"),
    ]

    def test_upstream_cases(self):
        for href, base, expected in self.UPSTREAM_CASES:
            with self.subTest(href=href, base=base):
                self.assertEqual(normalize_url(href, base), expected)

    def test_fragment_dropped_by_default(self):
        # Upstream test file expects the fragment kept; the cloned
        # function drops it unless keep_fragment=True.
        self.assertEqual(
            normalize_url("page.html#section", "http://example.com/"),
            "http://example.com/page.html")
        self.assertEqual(
            normalize_url("#fragment", "http://example.com/page.html"),
            "http://example.com/page.html")

    def test_fragment_kept_when_asked(self):
        self.assertEqual(
            normalize_url("page.html#section", "http://example.com/",
                          keep_fragment=True),
            "http://example.com/page.html#section")

    def test_empty_or_none_href_returns_none(self):
        # Upstream test file expects the base URL back; the cloned
        # function returns None (per its own docstring).
        self.assertIsNone(normalize_url("", "http://example.com/base/"))
        self.assertIsNone(normalize_url("", "http://example.com/base"))
        self.assertIsNone(normalize_url(None, "http://example.com/"))

    def test_tracking_params_dropped_and_query_sorted(self):
        self.assertEqual(
            normalize_url("page.html?utm_source=x&b=2&a=1",
                          "http://example.com/"),
            "http://example.com/page.html?a=1&b=2")

    def test_host_lowercased(self):
        self.assertEqual(
            normalize_url("page.html", "http://EXAMPLE.com/"),
            "http://example.com/page.html")

    def test_invalid_base_url_does_not_raise(self):
        # Upstream test file expects ValueError("Invalid base URL
        # format"); the cloned function never validates the base and
        # returns a URL instead. Defined, non-crashing result:
        self.assertEqual(
            normalize_url("page.html", "ftp://example.com/"),
            "ftp://example.com/page.html")
        self.assertEqual(
            normalize_url("page.html", "http:///path/"),
            "http:///path/page.html")

    def test_extra_drop_params(self):
        self.assertEqual(
            normalize_url("page.html?keep=1&dropme=2", "http://example.com/",
                          extra_drop_params=["dropme"]),
            "http://example.com/page.html?keep=1")

    def test_preserve_https_same_domain(self):
        self.assertEqual(
            normalize_url("http://example.com/page.html",
                          "https://example.com/",
                          preserve_https=True, original_scheme="https"),
            "https://example.com/page.html")


if __name__ == "__main__":
    unittest.main()
