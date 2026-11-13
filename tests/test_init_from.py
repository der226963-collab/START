"""--init-from: start a new training leg from a finished checkpoint (2026-11-12).

The large model finished 500 steps at best val 3.1210, still above the
medium baseline 3.0989, with the curve still falling — so the next leg
continues from those weights instead of from scratch. --resume cannot
do this: it requires the same total, because the LR schedule is a
function of step/total. --init-from loads the weights and starts a
fresh optimizer, fresh LR schedule and fresh step count, with the
checkpoint's architecture, size and tokenizer checked against the
run's before anything trains.
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
    return a == b


@unittest.skipIf(torch is None, "torch not installed")
class TestInitFrom(unittest.TestCase):
    def test_init_from_loads_weights_and_continues(self):
        import train_gpt
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            out_a = os.path.join(tmp, "a", "run")
            out_b = os.path.join(tmp, "b", "run")
            common = ["--size", "tiny", "--data",
                      os.path.join(REPO, "data", "corpus.txt"),
                      "--seed", "42"]
            first = _run_main(common + ["--steps", "3", "--out", out_a])
            first_losses = _step_losses(first)
            # Second leg from the first leg's checkpoint.
            second = _run_main(common + ["--steps", "3", "--out", out_b,
                                         "--init-from", out_a])
            self.assertIn("Initialized from", second)
            second_losses = _step_losses(second)
            # Continuity: the warm-started leg's first loss is
            # far below the cold leg's first loss (random init).
            self.assertLess(second_losses[0], first_losses[0])
            # The second leg's checkpoint JSON records init_from.
            json_b = json.loads(Path(out_b + ".json").read_text())
            self.assertEqual(json_b["init_from"], out_a)
            # And the second leg actually trained: its final
            # checkpoint differs from the first leg's.
            ckpt_a = torch.load(out_a + ".pt", map_location="cpu",
                                weights_only=True)
            ckpt_b = torch.load(out_b + ".pt", map_location="cpu",
                                weights_only=True)
            self.assertFalse(_tensors_equal(ckpt_a, ckpt_b),
                             "second leg's weights are unchanged from init")

    def test_init_from_rejects_mismatch_and_missing(self):
        import train_gpt
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "run")
            common = ["--size", "tiny", "--data",
                      os.path.join(REPO, "data", "corpus.txt"),
                      "--seed", "42"]
            _run_main(common + ["--steps", "3", "--out", out])
            # Wrong size: the checkpoint is tiny, the run is small.
            with self.assertRaises(SystemExit):
                _run_main(common + ["--size", "small", "--steps", "3",
                                    "--out", os.path.join(tmp, "run2"),
                                    "--init-from", out])
            # Missing checkpoint.
            with self.assertRaises(SystemExit):
                _run_main(common + ["--steps", "3",
                                    "--out", os.path.join(tmp, "run3"),
                                    "--init-from",
                                    os.path.join(tmp, "nope")])

    def test_resume_with_matching_init_from(self):
        import train_gpt
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            common = ["--size", "tiny", "--data",
                      os.path.join(REPO, "data", "corpus.txt"),
                      "--seed", "42"]
            out_a = os.path.join(tmp, "a", "run")
            _run_main(common + ["--steps", "3", "--out", out_a])
            # A leg started with --init-from, run uninterrupted.
            out_b = os.path.join(tmp, "b", "run")
            full = _run_main(common + ["--steps", "6", "--out", out_b,
                                       "--init-from", out_a])
            # The same leg, "crashed" during the step-5 eval, then
            # resumed with the SAME --init-from alongside --resume.
            out_c = os.path.join(tmp, "c", "run")
            calls = []
            orig_evaluate = train_gpt.evaluate

            def flaky_evaluate(*args, **kwargs):
                calls.append(1)
                if len(calls) >= 2:
                    raise RuntimeError("simulated crash")
                return orig_evaluate(*args, **kwargs)

            with mock.patch.object(train_gpt, "evaluate", flaky_evaluate):
                with self.assertRaises(RuntimeError):
                    _run_main(common + ["--steps", "6", "--out", out_c,
                                        "--init-from", out_a])
            state_path = str(train_gpt.run_state_path(out_c))
            resumed = _run_main(common + ["--steps", "6", "--out", out_c,
                                          "--init-from", out_a,
                                          "--resume", state_path])
            self.assertIn("Resumed from", resumed)
            self.assertEqual(_step_losses(resumed)[5],
                             _step_losses(full)[5])
            json_b = json.loads(Path(out_b + ".json").read_text())
            json_c = json.loads(Path(out_c + ".json").read_text())
            self.assertEqual(json_b["best_val_loss"],
                             json_c["best_val_loss"])
            ckpt_b = torch.load(out_b + ".pt", map_location="cpu",
                                weights_only=True)
            ckpt_c = torch.load(out_c + ".pt", map_location="cpu",
                                weights_only=True)
            self.assertTrue(_tensors_equal(ckpt_b, ckpt_c),
                            "resumed init leg weights differ from uninterrupted")

    def test_resume_rejects_mismatched_init_from(self):
        import train_gpt
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "run")
            common = ["--size", "tiny", "--data",
                      os.path.join(REPO, "data", "corpus.txt"),
                      "--seed", "42"]
            # A plain run (no --init-from) leaves a state file
            # whose saved init_from is None.
            _run_main(common + ["--steps", "3", "--out", out])
            state_path = str(train_gpt.run_state_path(out))
            # Resuming it WITH an --init-from is a mismatch.
            with self.assertRaises(SystemExit):
                _run_main(common + ["--steps", "3", "--out", out,
                                    "--resume", state_path,
                                    "--init-from", out])
            # And a leg started from checkpoint A cannot be
            # resumed with a different checkpoint B.
            out_b = os.path.join(tmp, "b", "run")
            _run_main(common + ["--steps", "3", "--out", out_b,
                                "--init-from", out])
            state_b = str(train_gpt.run_state_path(out_b))
            with self.assertRaises(SystemExit):
                _run_main(common + ["--steps", "3", "--out", out_b,
                                    "--resume", state_b,
                                    "--init-from", out_b])


if __name__ == "__main__":
    unittest.main()
