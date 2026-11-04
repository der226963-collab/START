"""MiniGPT checks: shape, causal masking, and that training lowers loss."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import torch
    from mini_ai.gpt import MiniGPT, GPTConfig, CharTokenizer
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False


@unittest.skipUnless(HAS_TORCH, "torch not installed (see requirements-gpt.txt)")
class TestMiniGPT(unittest.TestCase):
    def test_forward_shape_and_causality(self):
        text = "The garden grows food."
        tok = CharTokenizer(text)
        cfg = GPTConfig(vocab_size=len(tok), block_size=16, n_layer=1, n_head=2, n_embd=32)
        model = MiniGPT(cfg)
        x = torch.tensor([tok.encode(text[:16])])
        logits, loss = model(x, x)
        self.assertEqual(logits.shape, (1, 16, len(tok)))
        self.assertTrue(loss.item() > 0)
        # Changing a later token must not change an earlier prediction.
        x2 = x.clone()
        x2[0, -1] = (x2[0, -1] + 1) % len(tok)
        logits2, _ = model(x2)
        self.assertTrue(torch.allclose(logits[0, 0], logits2[0, 0], atol=1e-5))

    def test_training_reduces_loss(self):
        text = "abcabcabcabcabcabcabcabcabcabc"
        tok = CharTokenizer(text)
        data = torch.tensor(tok.encode(text * 20), dtype=torch.long)
        cfg = GPTConfig(vocab_size=len(tok), block_size=8, n_layer=1, n_head=2, n_embd=32)
        model = MiniGPT(cfg)
        opt = torch.optim.AdamW(model.parameters(), lr=5e-3)
        first = None
        for step in range(60):
            x = data[:32].reshape(4, 8)
            y = torch.roll(x, -1, dims=1)
            _, loss = model(x, y)
            if first is None:
                first = loss.item()
            opt.zero_grad()
            loss.backward()
            opt.step()
        self.assertLess(loss.item(), first)


if __name__ == "__main__":
    unittest.main()
