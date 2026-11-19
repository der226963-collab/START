"""Tests for the SmolLM2 loader and model.

The RoPE test is exact and distinguishes the rotate-half convention
(HF Llama, used here) from the interleaved convention in
model_modern.py. The load test needs the downloaded weights
(~/workspace/models/smollm2-360m/) and is skipped when absent.
"""
import math
import unittest

try:
    import torch

    from mini_ai.gpt.smollm2 import SmolLM2Config, SmolLM2Model, _apply_rope_llama, _rope_freqs

    HAS_TORCH = True
except ImportError:
    # System python has no torch; these tests run in the torch venv.
    torch = None
    HAS_TORCH = False


@unittest.skipUnless(HAS_TORCH, "torch not installed (see requirements-gpt.txt)")
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


@unittest.skipUnless(HAS_TORCH, "torch not installed (see requirements-gpt.txt)")
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


def _tiny_model():
    """A small random SmolLM2Model for generate() tests (no weights).

    Vocab 64 keeps the argmax dynamics fast and repeat-prone, which
    is what the repetition-penalty tests need.
    """
    torch.manual_seed(0)
    cfg = SmolLM2Config(vocab_size=64, hidden_size=32,
                        intermediate_size=64, num_hidden_layers=2,
                        num_attention_heads=4, num_key_value_heads=2,
                        max_position_embeddings=128)
    return SmolLM2Model(cfg)


def _fixed_logits_model(top_token, second_token, top_logit, second_logit,
                        rest=0.0):
    """A tiny model whose forward returns fixed logits every step.

    Token `top_token` has the highest logit, `second_token` the
    second-highest, everything else `rest`. At temperature 0 without
    a penalty this generates `top_token` forever (a deterministic
    loop); the penalty can only change the output by demoting an
    already-generated token.
    """
    model = _tiny_model()
    vocab = model.config.vocab_size

    def forward(idx, targets=None):
        batch, seq = idx.shape
        logits = torch.full((batch, seq, vocab), float(rest))
        logits[:, :, top_token] = float(top_logit)
        logits[:, :, second_token] = float(second_logit)
        return logits, None

    model.forward = forward
    return model


@unittest.skipUnless(HAS_TORCH, "torch not installed (see requirements-gpt.txt)")
class TestRepetitionPenalty(unittest.TestCase):
    def test_penalty_one_reproduces_old_behavior(self):
        model = _tiny_model()
        idx = torch.tensor([[1, 2, 3]], dtype=torch.long)
        out_default = model.generate(idx, 30, temperature=0.0)
        out_one = model.generate(idx, 30, temperature=0.0,
                                 repetition_penalty=1.0)
        self.assertTrue(torch.equal(out_default, out_one))

    def test_penalty_below_one_rejected(self):
        model = _tiny_model()
        idx = torch.tensor([[1, 2, 3]], dtype=torch.long)
        with self.assertRaises(ValueError):
            model.generate(idx, 5, temperature=0.0, repetition_penalty=0.9)
        with self.assertRaises(ValueError):
            model.generate(idx, 5, temperature=0.0, repetition_penalty=0.5)

    def test_penalty_breaks_loop_positive_logits(self):
        # Logits: token 5 at 10.0, token 6 at 9.5, rest 0.0.
        model = _fixed_logits_model(5, 6, 10.0, 9.5, rest=0.0)
        idx = torch.tensor([[1, 2, 3]], dtype=torch.long)
        plain = model.generate(idx, 30, temperature=0.0)
        self.assertTrue((plain[0, 3:] == 5).all())
        penalized = model.generate(idx, 30, temperature=0.0,
                                   repetition_penalty=1.2)
        self.assertFalse(torch.equal(plain, penalized))
        # Still valid generation: full length, tokens in vocab.
        self.assertEqual(penalized.shape, (1, 33))
        self.assertTrue(((penalized >= 0) & (penalized < 64)).all())

    def test_penalty_breaks_loop_negative_logits(self):
        # Same shape, but the top two logits are negative: the
        # penalty multiplies a negative logit, making it more
        # negative. Token 5 at -1.0, token 6 at -1.1, rest -10.0.
        model = _fixed_logits_model(5, 6, -1.0, -1.1, rest=-10.0)
        idx = torch.tensor([[1, 2, 3]], dtype=torch.long)
        plain = model.generate(idx, 30, temperature=0.0)
        self.assertTrue((plain[0, 3:] == 5).all())
        penalized = model.generate(idx, 30, temperature=0.0,
                                   repetition_penalty=1.2)
        self.assertFalse(torch.equal(plain, penalized))
        self.assertEqual(penalized.shape, (1, 33))

    def test_prompt_tokens_not_penalized(self):
        # Prompt contains token 5, which the fixed logits also favour
        # (5 at 10.0, 6 at 9.5). If prompt tokens were penalized, the
        # first generated token would be 6; only continuation tokens
        # are penalized, so the first generated token is 5.
        model = _fixed_logits_model(5, 6, 10.0, 9.5, rest=0.0)
        idx = torch.tensor([[5, 2, 3]], dtype=torch.long)
        out = model.generate(idx, 5, temperature=0.0,
                             repetition_penalty=1.2)
        self.assertEqual(int(out[0, 3]), 5)


@unittest.skipUnless(HAS_TORCH, "torch not installed (see requirements-gpt.txt)")
class TestNoRepeatNgram(unittest.TestCase):
    def test_ngram_zero_reproduces_old_behavior(self):
        model = _tiny_model()
        idx = torch.tensor([[1, 2, 3]], dtype=torch.long)
        out_default = model.generate(idx, 30, temperature=0.0)
        out_zero = model.generate(idx, 30, temperature=0.0,
                                  no_repeat_ngram_size=0)
        self.assertTrue(torch.equal(out_default, out_zero))

    def test_ngram_invalid_sizes_rejected(self):
        model = _tiny_model()
        idx = torch.tensor([[1, 2, 3]], dtype=torch.long)
        with self.assertRaises(ValueError):
            model.generate(idx, 5, temperature=0.0,
                           no_repeat_ngram_size=-1)
        with self.assertRaises(ValueError):
            model.generate(idx, 5, temperature=0.0,
                           no_repeat_ngram_size=1)

    def test_ngram_three_breaks_trigram_loop(self):
        # Logits: token 5 at 10.0, token 6 at 9.5, rest 0.0.
        # Without blocking this generates 5 forever; with trigram
        # blocking, once (5, 5, 5) exists, 5 is banned whenever the
        # last two generated tokens are (5, 5), so 6 must take over.
        model = _fixed_logits_model(5, 6, 10.0, 9.5, rest=0.0)
        idx = torch.tensor([[1, 2, 3]], dtype=torch.long)
        plain = model.generate(idx, 30, temperature=0.0)
        self.assertTrue((plain[0, 3:] == 5).all())
        blocked = model.generate(idx, 30, temperature=0.0,
                                 no_repeat_ngram_size=3)
        self.assertFalse(torch.equal(plain, blocked))
        # Still valid generation: full length, tokens in vocab.
        self.assertEqual(blocked.shape, (1, 33))
        self.assertTrue(((blocked >= 0) & (blocked < 64)).all())
        # The invariant itself: no trigram repeats in the continuation.
        cont = blocked[0, 3:].tolist()
        trigrams = [tuple(cont[i:i + 3]) for i in range(len(cont) - 2)]
        self.assertEqual(len(trigrams), len(set(trigrams)))

    def test_prompt_tokens_not_blocked(self):
        # Prompt [5, 6, 5, 2] contains the trigram (5, 6, 5). With
        # fixed logits favouring 5 then 6, the continuation runs
        # 5, 5, 5, 6, 5 — and the fifth token (out[0, 8]) is 5, which
        # completes the trigram (5, 6, 5) already in the prompt. If
        # prompt n-grams were (wrongly) included in the ban set, 5
        # would be banned there and 6 generated instead.
        model = _fixed_logits_model(5, 6, 10.0, 9.5, rest=0.0)
        idx = torch.tensor([[5, 6, 5, 2]], dtype=torch.long)
        out = model.generate(idx, 5, temperature=0.0,
                             no_repeat_ngram_size=3)
        self.assertEqual(int(out[0, 8]), 5)
        cont = out[0, 4:].tolist()
        trigrams = [tuple(cont[i:i + 3]) for i in range(len(cont) - 2)]
        self.assertIn((5, 6, 5), trigrams)

    def test_ngram_composes_with_penalty(self):
        # Both active at once: the loop still breaks, output stays
        # full-length and in-vocab.
        model = _fixed_logits_model(5, 6, 10.0, 9.5, rest=0.0)
        idx = torch.tensor([[1, 2, 3]], dtype=torch.long)
        out = model.generate(idx, 30, temperature=0.0,
                             repetition_penalty=1.2,
                             no_repeat_ngram_size=3)
        self.assertEqual(out.shape, (1, 33))
        self.assertTrue(((out >= 0) & (out < 64)).all())
        self.assertFalse((out[0, 3:] == 5).all())


@unittest.skipUnless(HAS_TORCH, "torch not installed (see requirements-gpt.txt)")
class TestMinNewTokens(unittest.TestCase):
    def test_min_zero_reproduces_old_behavior(self):
        model = _tiny_model()
        idx = torch.tensor([[1, 2, 3]], dtype=torch.long)
        out_default = model.generate(idx, 30, temperature=0.0)
        out_zero = model.generate(idx, 30, temperature=0.0,
                                  min_new_tokens=0)
        self.assertTrue(torch.equal(out_default, out_zero))

    def test_min_new_tokens_suppresses_eos_then_releases(self):
        # EOS (token 0) has the highest logit (10.0), token 5 is
        # second (9.5), rest 0.0. Without a minimum, generation
        # stops after one token (EOS). With min_new_tokens=5, the
        # first five generated tokens are 5, and the sixth is EOS
        # once the window lifts — EOS is deferred, not forbidden.
        model = _fixed_logits_model(0, 5, 10.0, 9.5, rest=0.0)
        idx = torch.tensor([[1, 2, 3]], dtype=torch.long)
        plain = model.generate(idx, 30, temperature=0.0, eos_id=0)
        self.assertEqual(plain.shape, (1, 4))
        self.assertEqual(int(plain[0, 3]), 0)
        delayed = model.generate(idx, 30, temperature=0.0, eos_id=0,
                                 min_new_tokens=5)
        self.assertEqual(delayed.shape, (1, 9))
        self.assertEqual(delayed[0, 3:8].tolist(), [5] * 5)
        self.assertEqual(int(delayed[0, 8]), 0)

    def test_min_new_tokens_invalid_rejected(self):
        model = _tiny_model()
        idx = torch.tensor([[1, 2, 3]], dtype=torch.long)
        with self.assertRaises(ValueError):
            model.generate(idx, 5, temperature=0.0, min_new_tokens=-1)
        with self.assertRaises(ValueError):
            model.generate(idx, 5, temperature=0.0, min_new_tokens=-20)

    def test_min_new_tokens_composes_with_penalty(self):
        # EOS top (10.0), token 5 second (9.5), penalty 1.2: the
        # penalty demotes 5 after it is generated (9.5 / 1.2 = 7.9,
        # still above rest 0.0), so the first five tokens stay 5
        # and the sixth is EOS once the window lifts.
        model = _fixed_logits_model(0, 5, 10.0, 9.5, rest=0.0)
        idx = torch.tensor([[1, 2, 3]], dtype=torch.long)
        out = model.generate(idx, 30, temperature=0.0, eos_id=0,
                             repetition_penalty=1.2, min_new_tokens=5)
        self.assertEqual(out.shape, (1, 9))
        self.assertEqual(out[0, 3:8].tolist(), [5] * 5)
        self.assertEqual(int(out[0, 8]), 0)


if __name__ == "__main__":
    unittest.main()
