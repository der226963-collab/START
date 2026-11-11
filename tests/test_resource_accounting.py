"""Tests for the ODYM resource-accounting adapter
(adapters/resource_accounting.py, Module 17).

ODYM is a dependency only (IndEcol/ODYM, MIT), installed from git
pinned to commit 9792c23 — never published to PyPI, so there is no
`pip install ODYM`. No ODYM code is copied here; these tests exercise
the installed library through the thin original adapter.

Run from core-spine/ with:
    .venv/bin/python -m unittest discover -s tests -v
"""

import json
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from adapters.resource_accounting import (  # noqa: E402
    ODYM_PINNED_COMMIT,
    ODYM_PINNED_COMMIT_SHORT,
    ODYM_VERSION,
    accounts_to_dict,
    build_system,
    check_balance,
    odym_version,
)
from adapters.statuses import InternalStatus  # noqa: E402


class TestOdymDependency(unittest.TestCase):
    def test_odym_imports_and_version(self):
        import odym

        self.assertEqual(odym_version(), ODYM_VERSION)
        self.assertEqual(ODYM_VERSION, "0.1.0")
        self.assertEqual(ODYM_PINNED_COMMIT_SHORT, "9792c23")
        self.assertTrue(
            ODYM_PINNED_COMMIT.startswith(ODYM_PINNED_COMMIT_SHORT)
        )

    def test_pinned_commit_is_a_full_sha(self):
        self.assertEqual(len(ODYM_PINNED_COMMIT), 40)
        int(ODYM_PINNED_COMMIT, 16)  # hex, not a branch name or "HEAD"


class TestSyntheticSystem(unittest.TestCase):
    def test_system_builds(self):
        system = build_system()
        self.assertEqual(
            [p.Name for p in system.ProcessList],
            ["Environment", "Field", "Storage"],
        )
        self.assertEqual(set(system.FlowDict), {"F_0_1", "F_1_2", "F_2_0"})
        self.assertEqual(set(system.StockDict), {"S_1", "S_2"})
        self.assertEqual(system.Time_Start, 2026)
        self.assertEqual(system.Time_End, 2028)
        self.assertEqual(system.Unit, "t")
        for flow in system.FlowDict.values():
            self.assertEqual(flow.Values.shape, (3, 1))

    def test_balance_passes_on_synthetic_case(self):
        result = check_balance(build_system())
        self.assertIs(result.status, InternalStatus.PASS)
        self.assertEqual(result.actual_value, 0.0)
        self.assertEqual(result.verdict.value, "pass")

    def test_odym_mass_balance_is_zero_everywhere(self):
        # The adapter's PASS is not its own arithmetic: it is ODYM's
        # MassBalance() itself, checked at every year/process/element.
        balance = build_system().MassBalance()
        self.assertEqual(balance.shape, (3, 3, 1))
        np.testing.assert_array_equal(balance, np.zeros((3, 3, 1)))

    def test_stock_changes_match_flow_differences(self):
        # The synthetic numbers are internally consistent by
        # construction: field stock change = fertiliser - harvest,
        # storage stock change = harvest - dispatch.
        system = build_system()
        f01 = system.FlowDict["F_0_1"].Values.flatten()
        f12 = system.FlowDict["F_1_2"].Values.flatten()
        f20 = system.FlowDict["F_2_0"].Values.flatten()
        np.testing.assert_array_equal(
            system.StockDict["S_1"].Values.flatten(), f01 - f12
        )
        np.testing.assert_array_equal(
            system.StockDict["S_2"].Values.flatten(), f12 - f20
        )


class TestBalanceFailureModes(unittest.TestCase):
    def test_deliberately_unbalanced_case_fails_never_passes(self):
        # Dispatch flow removed: storage stock change no longer matches
        # harvest - dispatch, so the balance must FAIL.
        unbalanced = build_system(
            flow_values={
                "F_0_1": [10.0, 12.0, 11.0],
                "F_1_2": [8.0, 10.0, 9.0],
                "F_2_0": [0.0, 0.0, 0.0],
            }
        )
        result = check_balance(unbalanced)
        self.assertIs(result.status, InternalStatus.FAIL)
        self.assertEqual(result.verdict.value, "fail")
        self.assertGreater(result.actual_value, 0.0)

    def test_small_imbalance_below_tolerance_passes(self):
        # A 1e-12 t discrepancy is floating-point noise, not a real
        # imbalance; the tolerance is stated, not hidden.
        noisy = build_system(
            stock_values={
                "S_1": [2.0, 2.0, 2.0],
                "S_2": [1.0 + 1e-12, 1.0, -1.0],
            }
        )
        self.assertIs(check_balance(noisy).status, InternalStatus.PASS)

    def test_imbalance_above_tolerance_fails(self):
        off = build_system(
            stock_values={
                "S_1": [2.0, 2.0, 2.0],
                "S_2": [1.0, 1.0, 0.0],  # 1 t of storage change missing
            }
        )
        self.assertIs(check_balance(off).status, InternalStatus.FAIL)

    def test_missing_system_is_unknown_never_pass(self):
        result = check_balance(None)
        self.assertIs(result.status, InternalStatus.UNKNOWN)
        self.assertEqual(result.verdict.value, "indeterminate")

    def test_empty_system_is_unknown_never_pass(self):
        empty = build_system(flow_values={}, stock_values={})
        result = check_balance(empty)
        self.assertIs(result.status, InternalStatus.UNKNOWN)
        self.assertEqual(result.verdict.value, "indeterminate")

    def test_nonfinite_values_are_unknown_never_pass(self):
        bad = build_system(
            flow_values={
                "F_0_1": [10.0, float("nan"), 11.0],
                "F_1_2": [8.0, 10.0, 9.0],
                "F_2_0": [7.0, 9.0, 10.0],
            }
        )
        result = check_balance(bad)
        self.assertIs(result.status, InternalStatus.UNKNOWN)


class TestGovernanceFlags(unittest.TestCase):
    def test_output_is_model_result_not_verified(self):
        out = accounts_to_dict(build_system())
        self.assertIs(out["verified"], False)
        self.assertIs(out["needs_human_decision"], True)
        self.assertIs(out["synthetic"], True)
        self.assertEqual(out["odym_version"], "0.1.0")
        self.assertEqual(out["odym_commit"], "9792c23")

    def test_output_is_plain_jsonable_data(self):
        out = accounts_to_dict(build_system())
        text = json.dumps(out)  # must not raise
        back = json.loads(text)
        self.assertEqual(back["flows_t_per_year"]["F_0_1"], [10.0, 12.0, 11.0])
        self.assertEqual(back["balance"]["status"], "PASS")


class TestExplicitArguments(unittest.TestCase):
    def test_systems_do_not_share_mutable_state(self):
        # MFAsystem's constructor defaults are mutable (ProcessList=[],
        # FlowDict={}). The adapter must never rely on them: two
        # independently built systems must own distinct collections,
        # and mutating one must not touch the other.
        first = build_system()
        second = build_system()
        self.assertIsNot(first.ProcessList, second.ProcessList)
        self.assertIsNot(first.FlowDict, second.FlowDict)
        self.assertIsNot(first.StockDict, second.StockDict)
        first.ProcessList.append(first.ProcessList[0])
        self.assertEqual(len(second.ProcessList), 3)
        first.FlowDict["F_9_9"] = first.FlowDict["F_0_1"]
        self.assertNotIn("F_9_9", second.FlowDict)

    def test_adapter_never_uses_constructor_defaults(self):
        # Direct proof: the defaults on the ODYM constructor are the
        # shared mutable objects the audit warned about, and our
        # systems do not alias them.
        import inspect

        import odym.classes as odym_classes

        sig = inspect.signature(odym_classes.MFAsystem.__init__)
        defaults = {
            name: param.default
            for name, param in sig.parameters.items()
            if param.default is not inspect.Parameter.empty
        }
        system = build_system()
        self.assertIsNot(system.ProcessList, defaults["ProcessList"])
        self.assertIsNot(system.FlowDict, defaults["FlowDict"])
        self.assertIsNot(system.StockDict, defaults["StockDict"])


if __name__ == "__main__":
    unittest.main()
