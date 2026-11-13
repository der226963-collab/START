"""Tests for the SmolLM2 loader and model.

The RoPE test is exact and distinguishes the rotate-half convention
(HF Llama, used here) from the interleaved convention in
model_modern.py. The load test needs the downloaded weights
(~/workspace/models/smollm2-360m/) and is skipped when absent.
"""
import math
import unittest

import torch

from mini_ai.gpt.smollm2 import SmolLM2Config, SmolLM2Model, _apply_rope_llama, _rope_freqs


class TestRope(unittest.TestCase):
    def test_rotate_half_one_hot(self):
        # head_dim 4, theta 10000, position 1. Pair j=0 rotates by 1 rad,
        # pair j=1 by 0.01 rad. A one-hot vector on dim 0 must land on
        # dims 0 and 2 (halves), NOT dims 0 and 1 (interleaved pairs).
        cos, sin = _rope_freqs(4, 10000.0, 2, torch.device("cpu"))
        x = torch.zeros(1, 1, 2, 4)
        x[0, 0, 1, 0] = 1.0
        out = _apply_rope_llama(x, cos, sin)
        self.assertAlmostEqual(out[0, 0, 1, 0].item(), math.cos(1.0), places=5)
        self.assertAlmostEqual(out[0, 0, 1, 1].item(), 0.0, places=5)
        self.assertAlmostEqual(out[0, 0, 1, 2].item(), math.sin(1.0), places=5)
        self.assertAlmostEqual(out[0, 0, 1, 3].item(), 0.0, places=5)
        # Position 0 is the identity.
        self.assertTrue(torch.allclose(out[0, 0, 0], x[0, 0, 0]))

    def test_param_count(self):
        cfg = SmolLM2Config()
        model = SmolLM2Model(cfg)
        self.assertEqual(model.count_parameters(), 361821120)


class TestLoad(unittest.TestCase):
    def test_load_pretrained(self):
        from pathlib import Path

        model_dir = Path("/home/hatch/workspace/models/smollm2-360m")
        if not (model_dir / "model.safetensors").exists():
            self.skipTest("SmolLM2 weights not downloaded")
        from mini_ai.gpt.smollm2 import load_pretrained

        model, config = load_pretrained(model_dir)
        self.assertEqual(model.count_parameters(), 361821120)
        idx = torch.tensor([[1, 2, 3, 4]], dtype=torch.long)
        logits, loss = model(idx)
        self.assertEqual(logits.shape, (1, 4, config.vocab_size))
        self.assertTrue(torch.isfinite(logits).all())


if __name__ == "__main__":
    unittest.main()
