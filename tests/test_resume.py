"""Resume support for long training runs (2026-11-11).

A 500-step large run takes many hours on this VM and runtime
restarts can replace the VM, so train_gpt.py can now save a
run state (model, optimizer, RNG, best checkpoint, args) and
continue from it, and mixture runs cache their tokens next
to --out. These tests prove a resumed run is the same run:
same per-step losses, same final weights, same optimizer
state as an uninterrupted run with the same seed.
"""
import io
import json
import os
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    import torch
except ImportError:
    torch = None

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STEP_RE = re.compile(r"step\s+(\d+)\s+train\s+([0-9.]+)")


def _run_main(argv):
    """Run train_gpt.main() with patched sys.argv, capturing stdout."""
    import train_gpt
    buf = io.StringIO()
    with mock.patch.object(sys, "argv", ["train_gpt.py"] + argv):
        with redirect_stdout(buf):
            train_gpt.main()
    return buf.getvalue()


def _step_losses(output):
    return {int(m.group(1)): float(m.group(2)) for m in STEP_RE.finditer(output)}


def _tensors_equal(a, b):
    if isinstance(a, torch.Tensor) and isinstance(b, torch.Tensor):
        return torch.equal(a, b)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(
            _tensors_equal(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(
            _tensors_equal(x, y) for x, y in zip(a, b))
    return a == b


@unittest.skipIf(torch is None, "torch not installed")
class TestResume(unittest.TestCase):
    def test_resume_matches_uninterrupted_run(self):
        import train_gpt
        with tempfile.TemporaryDirectory() as tmp:
            out_a = os.path.join(tmp, "a", "run")
            out_b = os.path.join(tmp, "b", "run")
            common = ["--size", "tiny", "--data",
                      os.path.join(REPO, "data", "corpus.txt"),
                      "--seed", "42"]
            # Uninterrupted 6 steps.
            full = _run_main(common + ["--steps", "6", "--out", out_a])
            # Same run, "crashed" during the step-5 eval: the
            # step-0 eval has already saved a state file with
            # next_step 1, so the resume continues from step 1.
            # (Resume needs the same total — the LR schedule
            # is a function of step/total — so a short run
            # cannot be resumed into a longer one; the crash
            # simulation below is the honest end-to-end test.)
            calls = []
            orig_evaluate = train_gpt.evaluate

            def flaky_evaluate(*args, **kwargs):
                calls.append(1)
                if len(calls) >= 2:
                    raise RuntimeError("simulated crash")
                return orig_evaluate(*args, **kwargs)

            with mock.patch.object(train_gpt, "evaluate", flaky_evaluate):
                with self.assertRaises(RuntimeError):
                    _run_main(common + ["--steps", "6", "--out", out_b])
            state_path = train_gpt.run_state_path(out_b)
            self.assertTrue(os.path.exists(state_path),
                            "no state file after the crashed leg")
            state = train_gpt.load_run_state(state_path)
            self.assertEqual(state["next_step"], 1)
            resumed = _run_main(common + ["--steps", "6", "--resume",
                                         str(state_path), "--out", out_b])
            self.assertIn("Resumed from", resumed)

            # Printed losses: eval points are step 0 and the
            # last step, so compare what both runs printed.
            full_losses = _step_losses(full)
            resumed_losses = _step_losses(resumed)
            self.assertEqual(resumed_losses[5], full_losses[5])

            # Final checkpoint JSONs agree on the last train
            # loss and the best validation loss.
            from pathlib import Path
            json_a = json.loads(Path(out_a + ".json").read_text())
            json_b = json.loads(Path(out_b + ".json").read_text())
            self.assertEqual(json_a["final_train_loss"],
                             json_b["final_train_loss"])
            self.assertEqual(json_a["best_val_loss"], json_b["best_val_loss"])

            # Strongest check: the final weights and the final
            # optimizer state are identical tensors. If the RNG
            # stream or the optimizer state had diverged on
            # resume, these would differ.
            ckpt_a = torch.load(out_a + ".pt", map_location="cpu",
                                weights_only=True)
            ckpt_b = torch.load(out_b + ".pt", map_location="cpu",
                                weights_only=True)
            self.assertTrue(_tensors_equal(ckpt_a, ckpt_b),
                            "resumed final weights differ from uninterrupted")
            state_a = train_gpt.load_run_state(
                train_gpt.run_state_path(out_a))
            state_b = train_gpt.load_run_state(
                train_gpt.run_state_path(out_b))
            self.assertTrue(
                _tensors_equal(state_a["optimizer_state"],
                               state_b["optimizer_state"]),
                "resumed optimizer state differs from uninterrupted")

    def test_resume_rejects_mismatched_args(self):
        import train_gpt
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "run")
            common = ["--size", "tiny", "--data",
                      os.path.join(REPO, "data", "corpus.txt"),
                      "--seed", "42"]
            _run_main(common + ["--steps", "3", "--out", out])
            state_path = str(train_gpt.run_state_path(out))
            # Different total steps: the LR schedule is a
            # function of step/total, so the total is fixed.
            with self.assertRaises(SystemExit):
                _run_main(common + ["--steps", "8", "--resume",
                                    state_path, "--out", out])
            # Different learning rate.
            with self.assertRaises(SystemExit):
                _run_main(common + ["--steps", "3", "--lr", "1e-3",
                                    "--resume", state_path, "--out", out])
            # Missing state file.
            with self.assertRaises(SystemExit):
                _run_main(common + ["--steps", "3", "--resume",
                                    os.path.join(tmp, "nope-state.pt"),
                                    "--out", out])

    def test_multi_optimizer_state_round_trip(self):
        from train_gpt import _MultiOptimizer
        from mini_ai.gpt.muon import Muon
        torch.manual_seed(0)
        lin = torch.nn.Linear(8, 8, bias=False)
        opt = _MultiOptimizer([
            (Muon([lin.weight], lr=0.02), "muon"),
            (torch.optim.AdamW([torch.nn.Parameter(torch.randn(4))],
                               lr=1e-3), "adamw"),
        ])
        loss = lin(torch.randn(4, 8)).sum()
        loss.backward()
        opt.step()
        saved = opt.state_dict()
        # A fresh identical optimizer restores the same state.
        torch.manual_seed(0)
        lin2 = torch.nn.Linear(8, 8, bias=False)
        opt2 = _MultiOptimizer([
            (Muon([lin2.weight], lr=0.02), "muon"),
            (torch.optim.AdamW([torch.nn.Parameter(torch.randn(4))],
                               lr=1e-3), "adamw"),
        ])
        opt2.load_state_dict(saved)
        self.assertTrue(_tensors_equal(opt2.state_dict(), saved))
        # And stepping after a load works.
        loss2 = lin2(torch.randn(4, 8)).sum()
        loss2.backward()
        opt2.step()
        self.assertFalse(torch.isnan(lin2.weight).any().item())


@unittest.skipIf(torch is None, "torch not installed")
class TestMixtureCache(unittest.TestCase):
    def test_round_trip_and_stale_hash(self):
        import train_gpt
        from mini_ai.gpt.bpe import BPETokenizer
        text = ("the garden grows green leaves " * 40
                + "the river runs fast and cold " * 40)
        code = ("fn main() { let x = 1; }\n" * 40
                + "def f(x): return x + 1\n" * 40)
        tokenizer = BPETokenizer.train(text + code, num_merges=20)
        textbook_train, textbook_val = train_gpt.encode_parts(
            tokenizer, [text])
        code_train, code_val = train_gpt.encode_parts(tokenizer, [code])
        train_parts, val_parts, _, _ = train_gpt.mix_tokens(
            textbook_train, textbook_val, code_train, code_val, 0.5)
        train_data = torch.tensor(train_parts, dtype=torch.long)
        val_data = torch.tensor(val_parts, dtype=torch.long)
        import hashlib
        meta = {
            "tokenizer": "bpe", "bpe_merges": 20, "bpe_sample_chars": 5000000,
            "code_ratio": 0.5,
            "data_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "code_sha256": hashlib.sha256(code.encode()).hexdigest(),
        }
        with tempfile.TemporaryDirectory() as tmp:
            base = train_gpt.mixture_cache_base(os.path.join(tmp, "run"))
            # Nothing cached yet.
            self.assertIsNone(train_gpt.load_mixture_cache(base, meta))
            train_gpt.save_mixture_cache(
                base, train_data, val_data, tokenizer,
                {**meta, "train_tokens": len(train_data),
                 "val_tokens": len(val_data)})
            # Matching meta loads identical tensors + tokenizer.
            hit = train_gpt.load_mixture_cache(base, meta)
            self.assertIsNotNone(hit)
            got_train, got_val, got_tok = hit
            self.assertTrue(torch.equal(got_train, train_data))
            self.assertTrue(torch.equal(got_val, val_data))
            self.assertEqual(got_tok.vocab, tokenizer.vocab)
            self.assertEqual(got_tok.merges, tokenizer.merges)
            # A changed code corpus is a stale cache, never reused.
            stale = dict(meta)
            stale["code_sha256"] = "0" * 64
            self.assertIsNone(train_gpt.load_mixture_cache(base, stale))
            # A changed ratio is stale too.
            stale2 = dict(meta)
            stale2["code_ratio"] = 0.7
            self.assertIsNone(train_gpt.load_mixture_cache(base, stale2))


if __name__ == "__main__":
    unittest.main()
