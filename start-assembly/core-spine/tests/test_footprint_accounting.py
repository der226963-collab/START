"""Tests for the pymrio footprint-accounting adapter
(adapters/footprint_accounting.py, Module 17).

pymrio is a dependency only (IndEcol/pymrio, LGPL-3.0), installed
from PyPI as pymrio==0.7.0 — verified on PyPI before installing
(after the ODYM surprise: the sweep's install claim is never trusted
without checking). No pymrio code is copied here; these tests exercise
the installed library through the thin original adapter, on a small
synthetic in-memory MRIO only. No download, load, or parse of a real
EXIOBASE / WIOD / EORA database is ever triggered — that is enforced
by the tests below (static source check + network-blocked build).

Run from core-spine/ with:
    .venv/bin/python -m unittest discover -s tests -v
"""

import json
import os
import socket
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pymrio  # noqa: E402

from adapters.footprint_accounting import (  # noqa: E402
    PYMRIO_LICENCE,
    PYMRIO_REPO,
    PYMRIO_VERSION,
    accounts_to_dict,
    build_system,
    check_footprint,
    pymrio_version,
)
from adapters.statuses import InternalStatus  # noqa: E402

_ADAPTER_PATH = os.path.join(
    os.path.dirname(__file__), "..", "adapters", "footprint_accounting.py"
)


class TestPymrioDependency(unittest.TestCase):
    def test_pymrio_imports_and_version(self):
        self.assertEqual(pymrio_version(), PYMRIO_VERSION)
        self.assertEqual(PYMRIO_VERSION, "0.7.0")
        self.assertEqual(PYMRIO_REPO, "IndEcol/pymrio")
        self.assertEqual(PYMRIO_LICENCE, "LGPL-3.0")

    def test_pymrio_licence_is_lgpl_in_installed_metadata(self):
        # The LICENSE file shipped in the wheel is the full LGPL-3.0
        # text; the PyPI classifier agrees. The README badge saying
        # "GPL v3" is wrong — the LICENSE file is authoritative.
        import importlib.metadata

        meta = importlib.metadata.metadata("pymrio")
        classifiers = meta.get_all("Classifier") or []
        self.assertTrue(
            any("LGPLv3" in c for c in classifiers),
            f"no LGPLv3 classifier in installed metadata: {classifiers}",
        )


class TestSyntheticSystem(unittest.TestCase):
    def test_system_builds_in_memory(self):
        system = build_system()
        self.assertEqual(list(system.x.values.flatten()), [53.0, 57.0, 59.0, 67.0])
        self.assertEqual(system.Z.shape, (4, 4))
        self.assertEqual(system.Y.shape, (4, 2))
        self.assertEqual(system.emissions.F.shape, (1, 4))

    def test_footprint_identity_passes(self):
        system = build_system()
        result = check_footprint(system)
        self.assertEqual(result.status, InternalStatus.PASS)
        self.assertAlmostEqual(result.actual_value, 0.0, places=12)
        self.assertEqual(result.unit, "t")

    def test_production_equals_consumption_total(self):
        # Trade cancels over all regions: total D_pba == total D_cba.
        system = build_system()
        pba_total = float(system.emissions.D_pba.values.sum())
        cba_total = float(system.emissions.D_cba.values.sum())
        self.assertAlmostEqual(pba_total, cba_total, places=9)
        self.assertAlmostEqual(pba_total, 3.7, places=9)

    def test_per_region_accounts(self):
        system = build_system()
        accounts = accounts_to_dict(system)
        self.assertAlmostEqual(
            accounts["production_based_co2_t"]["R1"], 3.0, places=9
        )
        self.assertAlmostEqual(
            accounts["production_based_co2_t"]["R2"], 0.7, places=9
        )
        self.assertAlmostEqual(
            accounts["consumption_based_co2_t"]["R1"], 2.44025416, places=6
        )
        self.assertAlmostEqual(
            accounts["consumption_based_co2_t"]["R2"], 1.25974584, places=6
        )

    def test_tampered_accounts_fail(self):
        # A deliberately inconsistent case: an emissions account
        # tampered with after calculation must FAIL, never PASS.
        system = build_system()
        system.emissions.D_cba.iloc[0, 0] += 1.0
        result = check_footprint(system)
        self.assertEqual(result.status, InternalStatus.FAIL)
        self.assertGreaterEqual(result.actual_value, 1.0)

    def test_missing_system_is_unknown(self):
        result = check_footprint(None)
        self.assertEqual(result.status, InternalStatus.UNKNOWN)

    def test_empty_system_is_unknown(self):
        # Build a normal system, then empty its Z frame: the check
        # must report UNKNOWN, never PASS, on an empty input.
        system = build_system()
        system.Z = pd.DataFrame()
        result = check_footprint(system)
        self.assertEqual(result.status, InternalStatus.UNKNOWN)

    def test_non_finite_values_are_unknown(self):
        f_bad = np.array([[2.0, np.nan, 0.5, 0.2]])
        system = build_system(f_values=f_bad)
        result = check_footprint(system)
        self.assertEqual(result.status, InternalStatus.UNKNOWN)

    def test_tolerance_boundary(self):
        system = build_system()
        # Residual is 2.2e-16 t in floating point, so it passes at a
        # 1e-12 t tolerance but not at exactly 0.0.
        self.assertEqual(
            check_footprint(system, tolerance=1e-12).status, InternalStatus.PASS
        )
        self.assertEqual(
            check_footprint(system, tolerance=0.0).status, InternalStatus.FAIL
        )
        # A tampered case fails even at a generous tolerance of 0.5 t.
        system.emissions.D_cba.iloc[0, 0] += 1.0
        self.assertEqual(
            check_footprint(system, tolerance=0.5).status, InternalStatus.FAIL
        )


class TestGovernance(unittest.TestCase):
    def test_accounts_are_model_results_not_verified(self):
        accounts = accounts_to_dict(build_system())
        self.assertFalse(accounts["verified"])
        self.assertTrue(accounts["needs_human_decision"])
        self.assertTrue(accounts["synthetic"])
        self.assertEqual(accounts["pymrio_licence"], "LGPL-3.0")

    def test_accounts_are_jsonable(self):
        accounts = accounts_to_dict(build_system())
        text = json.dumps(accounts)
        back = json.loads(text)
        self.assertFalse(back["verified"])
        self.assertTrue(back["needs_human_decision"])
        self.assertEqual(back["footprint_identity"]["status"], "PASS")


class TestNoDownloads(unittest.TestCase):
    def test_adapter_source_calls_no_download_load_or_parse(self):
        # Static enforcement, on the parsed AST (not raw text, so
        # the docstring naming the banned calls and the
        # FORBIDDEN_CALLS constant itself do not trip it): no call
        # in the adapter may name a pymrio download / load / parse
        # function for a real database.
        import ast

        with open(_ADAPTER_PATH, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        called = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                called.add(node.id)
            elif isinstance(node, ast.Attribute):
                called.add(node.attr)
        banned_exact = {
            "load_exiobase",
            "load_wiod",
            "load_eora",
            "load_all",
            "load_test",
            "get_repo_content",
        }
        for name in called:
            self.assertNotIn(name, banned_exact, f"adapter calls {name!r}")
            self.assertFalse(
                name.startswith("download_") or name.startswith("parse_"),
                f"adapter calls {name!r}",
            )

    def test_build_and_check_work_with_network_blocked(self):
        # Dynamic enforcement: with the socket blocked and every
        # pymrio download function monkeypatched to raise, the
        # adapter still builds and checks — it needs no network and
        # no real database.
        real_socket = socket.socket

        def _blocked(*args, **kwargs):
            raise AssertionError("network access attempted")

        download_names = [
            "download_eora26",
            "download_exiobase1",
            "download_exiobase2",
            "download_exiobase3",
            "download_gloria",
            "download_oecd",
            "download_wiod2013",
        ]
        saved = {}
        for name in download_names:
            saved[name] = getattr(pymrio, name, None)

            def _raise(*args, _n=name, **kwargs):
                raise AssertionError(f"pymrio.{_n} called")

            setattr(pymrio, name, _raise)
        socket.socket = _blocked
        try:
            system = build_system()
            result = check_footprint(system)
        finally:
            socket.socket = real_socket
            for name, fn in saved.items():
                setattr(pymrio, name, fn)
        self.assertEqual(result.status, InternalStatus.PASS)


if __name__ == "__main__":
    unittest.main()
