"""Tests for the CPU-portable scaling pieces: Muon, QK-norm,
trapezoidal schedule, gradient accumulation plumbing.

These need torch, so they skip cleanly on system python
where torch is not installed, like the other torch tests.
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
class TestMuon(unittest.TestCase):
    def test_orthogonalize_keeps_shape_and_near_orthogonal(self):
        from mini_ai.gpt.muon import orthogonalize
        # Square case: rows should be near-orthonormal.
        g = torch.randn(8, 8)
        out = orthogonalize(g)
        self.assertEqual(out.shape, g.shape)
        gram = out @ out.T
        eye = torch.eye(8)
        self.assertLess((gram - eye).abs().max().item(), 0.5)
        # Tall case: columns should be near-orthonormal.
        g2 = torch.randn(8, 4)
        out2 = orthogonalize(g2)
        self.assertEqual(out2.shape, g2.shape)
        gram2 = out2.T @ out2
        self.assertLess((gram2 - torch.eye(4)).abs().max().item(), 0.5)

    def test_muon_step_changes_params_without_nan(self):
        from mini_ai.gpt.muon import Muon
        lin = torch.nn.Linear(8, 8, bias=False)
        before = lin.weight.clone()
        opt = Muon([lin.weight], lr=0.02)
        loss = lin(torch.randn(4, 8)).sum()
        loss.backward()
        opt.step()
        self.assertFalse(torch.isnan(lin.weight).any().item())
        self.assertFalse(torch.equal(before, lin.weight))


@unittest.skipIf(torch is None, "torch not installed")
class TestQKNorm(unittest.TestCase):
    def test_qk_norm_forward_finite(self):
        from mini_ai.gpt.model_modern import ModernGPT, ModernConfig
        cfg = ModernConfig(vocab_size=20, n_layer=1, n_head=2, n_embd=16,
                           block_size=16, qk_norm=True)
        model = ModernGPT(cfg)
        idx = torch.randint(0, 20, (2, 8))
        logits, loss = model(idx, idx)
        self.assertEqual(logits.shape, (2, 8, 20))
        self.assertFalse(torch.isnan(loss).item())


@unittest.skipIf(torch is None, "torch not installed")
class TestSchedule(unittest.TestCase):
    def test_trapezoid_warmup_plateau_decay(self):
        if torch is None:
            self.skipTest("torch not installed")
        # train_gpt imports torch at module level, so import here.
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        import train_gpt
        base = 3e-3
        self.assertAlmostEqual(train_gpt.lr_at(0, 1000, base, "trapezoid"), 0.0)
        self.assertAlmostEqual(train_gpt.lr_at(500, 1000, base, "trapezoid"), base)
        last = train_gpt.lr_at(999, 1000, base, "trapezoid")
        self.assertLess(last, base)
        self.assertGreater(last, 0.0)
        # Cosine still behaves as before at the ends.
        self.assertAlmostEqual(train_gpt.lr_at(0, 1000, base, "cosine"), base)
        self.assertLess(train_gpt.lr_at(999, 1000, base, "cosine"), base)


if __name__ == "__main__":
    unittest.main()
