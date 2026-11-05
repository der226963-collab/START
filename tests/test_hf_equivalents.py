"""Tests for the Hugging Face-emphasis equivalent code batch.

Hugging Face repos checked 2026-11-04 (all Apache 2.0, so
direct copying with the notice kept would have been allowed):
tokenizers, transformers, datasets, smollm. We did not copy
them: tokenizers is Rust, and smollm's repo is model cards /
transformers usage, not a curation script. These tests cover
the original Python equivalents instead:
  - incremental BPE matches the naive full-rescan trainer
    on small texts, and round-trips
  - canonical Muon (Nesterov + sqrt(max(1, rows/cols)) scale)
    still moves parameters and produces finite values
  - curation drops duplicates and menu-like paragraphs
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    import torch
except ImportError:
    torch = None


class TestFastBPE(unittest.TestCase):
    def test_matches_naive_and_roundtrips(self):
        from collections import Counter
        from mini_ai.gpt.bpe import BPETokenizer

        def naive(text, num_merges):
            tokens = list(text)
            vocab = sorted(set(tokens))
            merges = []
            for _ in range(num_merges):
                pairs = Counter()
                for i in range(len(tokens) - 1):
                    pairs[(tokens[i], tokens[i + 1])] += 1
                if not pairs:
                    break
                (a, b), c = pairs.most_common(1)[0]
                if c < 2:
                    break
                merged = a + b
                merges.append([a, b])
                if merged not in vocab:
                    vocab.append(merged)
                nt, i = [], 0
                while i < len(tokens):
                    if i < len(tokens) - 1 and tokens[i] == a and tokens[i + 1] == b:
                        nt.append(merged)
                        i += 2
                    else:
                        nt.append(tokens[i])
                        i += 1
                tokens = nt
            return merges, vocab

        for text in ["hello world hello world", "aaaa bbbb aaaa bbbb cccc"]:
            tok = BPETokenizer.train(text, num_merges=50)
            merges, vocab = naive(text, 50)
            self.assertEqual(tok.merges, merges)
            self.assertEqual(tok.vocab, vocab)
            self.assertEqual(tok.decode(tok.encode(text)), text)


@unittest.skipIf(torch is None, "torch not installed")
class TestCanonicalMuon(unittest.TestCase):
    def test_nesterov_step_finite(self):
        from mini_ai.gpt.muon import Muon
        p = torch.nn.Parameter(torch.randn(8, 8))
        opt = Muon([p], lr=0.02)
        p.grad = torch.randn(8, 8)
        before = p.detach().clone()
        opt.step()
        self.assertFalse(torch.isnan(p).any().item())
        self.assertFalse(torch.equal(before, p.detach()))


class TestCuration(unittest.TestCase):
    def test_dedup_and_filter(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
        from curate_text import curate
        good = "Climate change is driven by greenhouse gases in the atmosphere over long periods of time."
        text = f"{good}\n\n{good}\n\nHome About Contact Menu\n\n{good}"
        out, kept, dup, filt = curate(text)
        self.assertEqual(kept, 1)
        self.assertEqual(dup, 2)
        self.assertIn("Climate change", out)


if __name__ == "__main__":
    unittest.main()
