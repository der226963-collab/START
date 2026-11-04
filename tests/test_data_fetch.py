"""Tests for the propose-and-approve fetcher.

No test hits the live internet: downloads are mocked, so these
tests check the gates (allowlist, licence, staging-only,
approval-required) rather than any particular site.
"""
import json
import tempfile
import unittest
from pathlib import Path

from mini_ai.data_fetch import (
    approve_fetch,
    clean_text,
    list_staged,
    propose_fetch,
)


def fake_download(url):
    return ("*** START OF THE PROJECT GUTENBERG EBOOK Test ***\n"
            + "Hello science world.\n" * 10
            + "*** END OF THE PROJECT GUTENBERG EBOOK Test ***")


class TestDataFetch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.staging = Path(self.tmp.name) / "staging"
        self.expanded = Path(self.tmp.name) / "expanded"

    def tearDown(self):
        self.tmp.cleanup()

    def test_non_allowlist_host_is_refused(self):
        with self.assertRaises(ValueError):
            propose_fetch("https://example.com/book.txt", "Public domain (US)",
                          "Test", self.staging, _download_fn=fake_download)

    def test_http_is_refused(self):
        with self.assertRaises(ValueError):
            propose_fetch("http://www.gutenberg.org/book.txt", "Public domain (US)",
                          "Test", self.staging, _download_fn=fake_download)

    def test_unallowed_licence_is_refused(self):
        with self.assertRaises(ValueError):
            propose_fetch("https://www.gutenberg.org/book.txt", "All rights reserved",
                          "Test", self.staging, _download_fn=fake_download)

    def test_propose_writes_staging_only_not_expanded(self):
        prov = propose_fetch("https://www.gutenberg.org/files/2009/2009-0.txt",
                             "Public domain (US)", "Origin of Species",
                             self.staging, _download_fn=fake_download)
        self.assertTrue((self.staging / prov["staged_file"]).exists())
        self.assertFalse((self.expanded / prov["staged_file"]).exists())
        self.assertFalse(prov["approved"])
        self.assertEqual(prov["licence"], "Public domain (US)")
        self.assertIn("Hello science world", (self.staging / prov["staged_file"]).read_text())
        self.assertNotIn("START OF THE PROJECT GUTENBERG", (self.staging / prov["staged_file"]).read_text())

    def test_approve_requires_approved_flag(self):
        prov = propose_fetch("https://www.gutenberg.org/files/2009/2009-0.txt",
                             "Public domain (US)", "Origin of Species",
                             self.staging, _download_fn=fake_download)
        with self.assertRaises(ValueError):
            approve_fetch(prov["staged_file"], self.staging, self.expanded, approved=False)
        self.assertFalse((self.expanded / prov["staged_file"]).exists())

    def test_approve_moves_and_audits(self):
        prov = propose_fetch("https://www.gutenberg.org/files/2009/2009-0.txt",
                             "Public domain (US)", "Origin of Species",
                             self.staging, _download_fn=fake_download)
        out = approve_fetch(prov["staged_file"], self.staging, self.expanded, approved=True)
        self.assertTrue(out["approved"])
        self.assertTrue((self.expanded / prov["staged_file"]).exists())
        self.assertFalse((self.staging / prov["staged_file"]).exists())
        audit = (self.staging / "fetch_audit.jsonl").read_text()
        self.assertIn('"action": "propose"', audit)
        self.assertIn('"action": "approve"', audit)

    def test_list_staged(self):
        propose_fetch("https://www.gutenberg.org/files/2009/2009-0.txt",
                      "Public domain (US)", "Origin of Species",
                      self.staging, _download_fn=fake_download)
        listed = list_staged(self.staging)
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["title"], "Origin of Species")

    def test_clean_text_strips_html_tags(self):
        cleaned = clean_text("<html><body><p>Hello <b>science</b></p></body></html>")
        self.assertIn("Hello science", cleaned)
        self.assertNotIn("<p>", cleaned)

    def test_fetcher_is_protected_from_self_edit(self):
        from mini_ai.self_edit import PROTECTED

        self.assertIn("mini_ai/data_fetch.py", PROTECTED)
        self.assertIn("tests/test_data_fetch.py", PROTECTED)


if __name__ == "__main__":
    unittest.main()
