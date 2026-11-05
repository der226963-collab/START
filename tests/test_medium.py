"""Medium model size (2026-11-04, programming-language wave).

The medium config exists in train_gpt.py SIZES and builds
a ModernGPT that forwards correctly. It is not a training
quality test — a 20-step medium run on the full expanded
corpus gave val 4.2860 with gibberish generation, as
expected at 20 steps; the point here is that the size
config is valid and does not crash on construction or
a forward pass.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    import torch
except ImportError:
    torch = None


@unittest.skipIf(torch is None, "torch not installed")
class TestMedium(unittest.TestCase):
    def test_medium_config_forward(self):
        from train_gpt import SIZES
        from mini_ai.gpt.model_modern import ModernGPT, ModernConfig
        self.assertIn("medium", SIZES)
        cfg = ModernConfig(vocab_size=50, tie_weights=True, **SIZES["medium"])
        model = ModernGPT(cfg)
        idx = torch.randint(0, 50, (1, 16))
        logits, loss = model(idx, idx)
        self.assertEqual(logits.shape, (1, 16, 50))
        self.assertFalse(torch.isnan(loss).item())


if __name__ == "__main__":
    unittest.main()
