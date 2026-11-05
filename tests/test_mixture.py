"""Separate code corpus with a mixture ratio (2026-11-04).

Tests the mix_tokens rule in train_gpt.py, without running
a training job: ratio 0 returns textbooks only, ratio 1
returns code only, ratio 0.5 on 100 textbook + 10 code
tokens gives 100 textbook + 100 code tokens (code repeated
10x, reported as used), and val follows the same rule.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from train_gpt import mix_tokens
except ImportError:  # torch not installed in system python
    mix_tokens = None


@unittest.skipIf(mix_tokens is None, "torch not installed")
class TestMixture(unittest.TestCase):
    def test_ratio_zero(self):
        train, val, used_t, used_v = mix_tokens([1, 2, 3], [4], [9, 9], [8], 0.0)
        self.assertEqual((train, val, used_t, used_v), ([1, 2, 3], [4], 0, 0))

    def test_ratio_one(self):
        train, val, used_t, used_v = mix_tokens([1, 2, 3], [4], [9, 9], [8], 1.0)
        self.assertEqual((train, val), ([9, 9], [8]))

    def test_ratio_half_repeats_code(self):
        textbook = list(range(100))
        code = list(range(10))
        train, val, used_t, used_v = mix_tokens(textbook, list(range(20)), code, list(range(5)), 0.5)
        self.assertEqual(len(train), 200)
        self.assertEqual(used_t, 100)
        self.assertEqual(train[:100], textbook)
        self.assertEqual(train[100:], code * 10)
        self.assertEqual(len(val), 40)
        self.assertEqual(used_v, 20)

    def test_empty_code_raises(self):
        with self.assertRaises(ValueError):
            mix_tokens([1], [2], [], [], 0.5)


if __name__ == "__main__":
    unittest.main()
