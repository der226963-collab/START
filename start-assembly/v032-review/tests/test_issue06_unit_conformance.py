"""ISSUE-06 conformance: every Python `_UNITS` key against the Rust binary.

Enumerates the Python registry itself (never a hand-copied subset), runs
each unit through Python `Constraint.evaluate` and through the built
`start-kernel` binary, and requires the two to agree. Decision per unit,
for every Python `_UNITS` key: ACCEPT and convert within its dimension —
there is no Python key Rust rejects. A future Python key added without a
Rust entry fails here (Rust answers UNKNOWN_UNIT where Python passes).

Run: python -m unittest discover -s tests -v   (from start_v03_work/)
after `cargo build` in components/rust-kernels (cargo test does NOT
relink the binary, so build it explicitly first). If the binary is older
than lib.rs it is stale and the live tests skip rather than fail on a
stale build; the Rust-side conformance test
(`rust_registry_matches_python_registry_exactly` in lib.rs) covers the
registry directly and has no such staleness.
"""
from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

from contracts.constraints import Constraint
from contracts.units import _UNITS

ROOT = Path(__file__).resolve().parent.parent
BINARY = ROOT / "components" / "rust-kernels" / "target" / "debug" / "start-kernel"
LIB_RS = ROOT / "components" / "rust-kernels" / "src" / "lib.rs"

# One discriminating same-unit case per unit: value 8 <= bound 10 PASS,
# value 12 <= bound 10 FAIL. Same-unit cases exercise registry membership
# (unknown unit -> UNKNOWN, never PASS) without depending on conversion.
SAME_UNIT_CASES = [(8, 10, "PASS"), (12, 10, "FAIL")]

# Cross-unit conversion cases (value, value_unit, bound, bound_unit):
# the value converts to 8 in the bound's unit (PASS) and, where listed
# second, to 20 (FAIL) — a no-conversion evaluator would get the FAIL
# case wrong. Factors are Python's own (dimension base units).
CONVERSION_CASES = [
    (8, "m²", 0.001, "ha"),      # 8 m² = 0.0008 ha
    (20, "m²", 0.001, "ha"),     # 20 m² = 0.002 ha > 0.001 ha
    (0.0008, "ha", 10, "m²"),    # 0.0008 ha = 8 m²
    (8, "kcal", 0.008, "Mcal"),  # 8 kcal = 0.008 Mcal
    (0.008, "Mcal", 10, "kcal"),  # 0.008 Mcal = 8 kcal
    (8, "kWh", 10000, "kcal"),   # 8 kWh = 6883.37 kcal
    (20, "kWh", 10000, "kcal"),  # 20 kWh = 17208.41 kcal > 10000
    (8, "MWh", 10000, "kWh"),    # 8 MWh = 8000 kWh
    (8, "people", 10, "person"),  # person/people 1:1 (dimension "people")
    (12, "people", 10, "person"),
]


def run_rust(requests: list[dict]) -> list[dict]:
    inp = "\n".join(json.dumps(r) for r in requests)
    proc = subprocess.run([str(BINARY)], input=inp, capture_output=True,
                          text=True, timeout=30)
    assert proc.returncode == 0, f"start-kernel exited {proc.returncode}: {proc.stderr}"
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert len(lines) == len(requests), f"expected {len(requests)} results, got {len(lines)}"
    return [json.loads(ln) for ln in lines]


def python_status(value, value_unit, bound, bound_unit) -> str:
    c = Constraint(constraint_id="c", name="c", operator="<=",
                   bound=bound, unit=bound_unit)
    return c.evaluate(value, value_unit).name


def rust_request(i, value, value_unit, bound, bound_unit) -> dict:
    return {"schema_version": "1.0.0", "constraint_id": f"c{i}",
            "operator": "<=", "value": value, "value_unit": value_unit,
            "bound": bound, "bound_unit": bound_unit, "tolerance": 0}


class Issue06ConformanceTests(unittest.TestCase):
    def setUp(self):
        if not BINARY.exists():
            self.skipTest("start-kernel binary not built; run cargo build first")
        if BINARY.stat().st_mtime < LIB_RS.stat().st_mtime:
            self.skipTest("start-kernel binary is older than lib.rs; rebuild it first")

    def test_every_python_unit_accepted_by_rust_same_unit(self):
        """Every _UNITS key: Rust agrees with Python on 8<=10 PASS, 12<=10 FAIL."""
        requests, expected = [], []
        for unit in sorted(_UNITS):
            for value, bound, status in SAME_UNIT_CASES:
                requests.append(rust_request(len(requests), value, unit, bound, unit))
                expected.append((unit, value, status))
        results = run_rust(requests)
        for (unit, value, status), out in zip(expected, results):
            self.assertEqual(python_status(value, unit, 10, unit), status,
                             f"Python disagrees with itself for {unit}")
            self.assertEqual(out["status"], status,
                             f"Rust {unit} {value}<=10: got {out['status']}/{out['reason_code']}, want {status}")
            if status == "PASS":
                self.assertEqual(out["reason_code"], "OK")

    def test_conversion_cases_agree(self):
        """Cross-unit conversions in the new non-rate units agree, both directions."""
        requests = [rust_request(i, v, vu, b, bu)
                    for i, (v, vu, b, bu) in enumerate(CONVERSION_CASES)]
        results = run_rust(requests)
        for (value, vu, bound, bu), out in zip(CONVERSION_CASES, results):
            expected = python_status(value, vu, bound, bu)
            self.assertEqual(out["status"], expected,
                             f"Rust {value} {vu} <= {bound} {bu}: got "
                             f"{out['status']}/{out['reason_code']}, Python {expected}")

    def test_registry_decision_is_accept_for_every_python_key(self):
        """Explicit per-unit decision table: ACCEPT (convert in-dimension)
        for every Python _UNITS key. No Python key is rejected by Rust."""
        self.assertEqual(len(_UNITS), 24, "Python registry grew/shrank; update the decision table")
        for unit in sorted(_UNITS):
            out = run_rust([rust_request(0, 8, unit, 10, unit)])[0]
            self.assertNotEqual(out["reason_code"], "UNKNOWN_UNIT",
                                f"Rust rejects Python unit {unit}")
            self.assertEqual(out["status"], "PASS", f"Rust {unit} 8<=10")


if __name__ == "__main__":
    unittest.main()
