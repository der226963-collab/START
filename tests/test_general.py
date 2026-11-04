"""Tests for the general-agent scaffold and modern transformer.

These are unittest tests, so `python -m unittest discover -s tests`
picks them up. They check structure and routing, not intelligence:
a scaffold that routes to the wrong tool, or claims AGI, fails.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mini_ai.agent import Agent, Memory, retrieve


class TestRetrieval(unittest.TestCase):
    def test_retrieve_finds_soil_for_phosphorus(self):
        results = retrieve("phosphorus boundary soil", "data", top_k=3)
        self.assertTrue(results)
        self.assertTrue(any("soil" in r["file"] for r in results))

    def test_retrieve_empty_query_returns_empty(self):
        self.assertEqual(retrieve("the", "data"), [])


class TestAgent(unittest.TestCase):
    def setUp(self):
        self.agent = Agent(data_dir="data", memory=Memory())

    def test_phosphorus_question_calls_limits_check(self):
        result = self.agent.run("What is the phosphorus limit for a plan at 5.0 phosphorus?")
        self.assertTrue(result["needs_human_decision"])
        self.assertFalse(result["is_agi"])
        self.assertIn("check_plan_limits", str(result["trace"]))

    def test_food_question_calls_food_balance(self):
        result = self.agent.run("What is the global food balance?")
        self.assertIn("food_balance", str(result["trace"]))

    def test_backtest_question_calls_backtest(self):
        result = self.agent.run("Backtest a predictive model for climate")
        self.assertIn("backtest_climate", str(result["trace"]))

    def test_memory_records_run(self):
        self.agent.run("What is the phosphorus limit?")
        self.assertTrue(self.agent.memory.recent(1))

    def test_trace_has_critique(self):
        result = self.agent.run("What is the phosphorus limit?")
        self.assertEqual(result["trace"][-1]["action"], "self_critique")


class TestBPE(unittest.TestCase):
    def test_bpe_roundtrip_and_compression(self):
        from mini_ai.gpt.bpe import BPETokenizer

        text = "climate climate climate soil soil water water water"
        tok = BPETokenizer.train(text, num_merges=50)
        ids = tok.encode(text)
        self.assertEqual(tok.decode(ids), text)
        self.assertLess(len(ids), len(text))


class TestModernModel(unittest.TestCase):
    def test_modern_forward_and_generate(self):
        try:
            import torch
        except ImportError:
            self.skipTest("torch not installed (see requirements-gpt.txt)")

        from mini_ai.gpt.model_modern import ModernConfig, ModernGPT

        cfg = ModernConfig(vocab_size=65, n_layer=2, n_head=4, n_embd=64, block_size=64)
        model = ModernGPT(cfg)
        idx = torch.randint(0, 65, (2, 16))
        logits, loss = model(idx, idx)
        self.assertEqual(logits.shape, (2, 16, 65))
        self.assertTrue(loss.item() > 0)
        out = model.generate(idx[:, :8], max_new_tokens=4, temperature=0)
        self.assertEqual(out.shape[1], 12)


if __name__ == "__main__":
    unittest.main()
