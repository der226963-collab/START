"""ISSUE-27 persistence: versioned JSON envelopes, atomic saves.

Covers ``persistence/envelope.py`` (``save_envelope`` /
``load_envelope`` / ``KINDS``): round-trips for every kind, the exact
four envelope keys with the canonical schema version, same-major
version acceptance vs major-mismatch rejection, corrupt/missing/
wrong-kind files, kind-specific payload shape, atomicity (a failed
``os.replace`` leaves no target file; a refused overwrite leaves the
old file byte-identical), and verbatim result persistence — a
nutrients nitrogen-only style result keeps ``UNKNOWN`` unknown.

Run: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import logging
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from adapters.python.contracts import SCHEMA_VERSION
from persistence import KINDS, load_envelope, save_envelope
from persistence.envelope import ENVELOPE_KEYS

# Payloads used across the round-trip tests: one per kind.
PLAN_REQUEST = {
    "phosphorus_application_tg_per_year": 5.0,
    "food_kcal_per_capita_per_day": 2600,
    "planning_need_kcal_per_capita_per_day": 2500,
    "paid_work_hours_per_week": 40,
}
SCENARIO = {
    "scenario_id": "less-phosphorus",
    "name": "Less phosphorus",
    "description": "Apply 5 Tg/yr instead of the snapshot 18.2 Tg/yr.",
    "assumptions": ["uptake and losses as caller-stated"],
    "proposed_changes": {"phosphorus_applied_tg_per_year": 5.0},
    "geography": "global",
    "period": "2025",
    "source_ids": ["snapshot:phosphorus_application_to_cropland:2025"],
    "metadata": {},
}
# A nutrients nitrogen-only style engine result: nitrogen fixation has
# no stored boundary, so a nitrogen-only request cannot complete and
# the evaluation stays UNKNOWN — never PASS, never invented. Modelled
# on the real PlanningEngine result shape (see
# tests/test_issue34_nutrients.py).
NITROGEN_ONLY_RESULT = {
    "calculation_ok": False,
    "verified": False,
    "verified_ok": False,
    "ok": False,
    "domain": "nutrients",
    "validation": {"ok": False, "problems": ["nitrogen_uptake_tg_per_year is required"]},
    "calculation": {
        "calculation_status": "INSUFFICIENT_INPUT",
        "missing_fields": ["nitrogen_uptake_tg_per_year", "nitrogen_losses_tg_per_year"],
        "metrics": {
            "nitrogen_fixation_tg_per_year": 165.0,
            "nitrogen_boundary_tg_per_year": None,
        },
        "display_metrics": {},
        "assumptions": [],
        "limitations": ["Validation failed; calculation was not run."],
    },
    "evaluation": {
        "overall_status": "UNKNOWN",
        "constraint_results": [
            {
                "constraint_id": "nitrogen_fixation_tg_per_year",
                "status": "UNKNOWN",
                "explanation": "nitrogen fixation has no stored boundary",
                "source_ids": ["snapshot:nitrogen_fixation:2025"],
            }
        ],
        "warnings": ["Validation failed; calculation not run."],
    },
    "uncertainty": ["No calculation was performed because validation failed."],
    "verification": {"verified": False, "status": "PARTIALLY_VERIFIED"},
    "constraints_identified": ["nitrogen_fixation_tg_per_year"],
    "needs_human_decision": True,
    "limitations": ["Validation failed; calculation was not run."],
    "note": "Deterministic planning result only. No allocation, approval or decision has been made.",
}
PLAN_OVERRIDES = {"phosphorus_application_tg_per_year": 6.2}

PAYLOADS = {
    "plan_request": PLAN_REQUEST,
    "scenario": SCENARIO,
    "result": NITROGEN_ONLY_RESULT,
    "plan_overrides": PLAN_OVERRIDES,
}


def _craft_envelope(path: Path, *, schema_version=SCHEMA_VERSION,
                    kind="result", payload=None, omit=()):
    """Write an envelope by hand (bypassing save_envelope) for
    load-side tests: version forging, missing keys, unknown kinds."""
    envelope = {
        "schema_version": schema_version,
        "kind": kind,
        "saved_at": "2026-11-14T00:00:00Z",
        "payload": NITROGEN_ONLY_RESULT if payload is None else payload,
    }
    for key in omit:
        envelope.pop(key, None)
    path.write_text(json.dumps(envelope), encoding="utf-8")
    return path


class PersistenceTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _path(self, name="out.json"):
        return self.dir / name


class KindsTests(PersistenceTestCase):
    def test_kinds_are_exactly_the_four_cli_kinds(self):
        self.assertEqual(
            KINDS, {"plan_request", "scenario", "result", "plan_overrides"})
        self.assertIsInstance(KINDS, frozenset)

    def test_envelope_keys_are_exactly_the_four(self):
        self.assertEqual(
            ENVELOPE_KEYS, {"schema_version", "kind", "saved_at", "payload"})


class SaveTests(PersistenceTestCase):
    def test_save_returns_the_path_written(self):
        target = self._path()
        returned = save_envelope(target, "plan_request", PLAN_REQUEST)
        self.assertEqual(returned, target)
        self.assertIsInstance(returned, Path)
        self.assertTrue(target.is_file())

    def test_save_rejects_unknown_kind(self):
        with self.assertRaises(ValueError) as ctx:
            save_envelope(self._path(), "bogus-kind", {})
        self.assertIn("bogus-kind", str(ctx.exception))
        self.assertFalse(self._path().exists())

    def test_save_rejects_non_dict_payload(self):
        for bad in ([1, 2], "payload", 42, None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                save_envelope(self._path(), "result", bad)
        self.assertFalse(self._path().exists())

    def test_save_rejects_non_json_serialisable_payload(self):
        with self.assertRaises(ValueError):
            save_envelope(self._path(), "result", {"domain": {1, 2}})
        self.assertFalse(self._path().exists())

    def test_save_to_missing_parent_dir_raises_without_creating_it(self):
        # No hidden default store, no auto-created directories: the
        # caller chooses (and creates) the directory.
        with self.assertRaises(FileNotFoundError):
            save_envelope(self.dir / "no-such-dir" / "out.json",
                          "result", NITROGEN_ONLY_RESULT)
        self.assertFalse((self.dir / "no-such-dir").exists())


class RoundTripTests(PersistenceTestCase):
    def test_round_trip_returns_equal_payload_for_every_kind(self):
        for kind, payload in PAYLOADS.items():
            with self.subTest(kind=kind):
                target = self._path(f"{kind}.json")
                save_envelope(target, kind, payload)
                loaded = load_envelope(target)
                self.assertEqual(loaded["payload"], payload)
                self.assertEqual(loaded["kind"], kind)
                self.assertEqual(loaded["schema_version"], SCHEMA_VERSION)

    def test_saved_file_contains_all_four_keys_with_canonical_version(self):
        target = self._path()
        save_envelope(target, "scenario", SCENARIO)
        raw = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(set(raw.keys()), ENVELOPE_KEYS)
        self.assertEqual(raw["schema_version"], SCHEMA_VERSION)
        # saved_at is UTC ISO-8601 with a Z suffix.
        self.assertTrue(raw["saved_at"].endswith("Z"))
        parsed = datetime.fromisoformat(raw["saved_at"].replace("Z", "+00:00"))
        self.assertIsNotNone(parsed.tzinfo)

    def test_persisted_result_is_verbatim_statuses_unchanged(self):
        target = self._path("result.json")
        save_envelope(target, "result", NITROGEN_ONLY_RESULT)
        loaded = load_envelope(target)
        payload = loaded["payload"]
        self.assertEqual(payload, NITROGEN_ONLY_RESULT)
        # The nitrogen UNKNOWN is preserved, never upgraded to PASS
        # and never rewritten: bound-less nitrogen stays unknown.
        self.assertEqual(payload["evaluation"]["overall_status"], "UNKNOWN")
        self.assertEqual(
            payload["evaluation"]["constraint_results"][0]["status"], "UNKNOWN")
        self.assertEqual(
            payload["calculation"]["calculation_status"], "INSUFFICIENT_INPUT")
        self.assertIsNone(
            payload["calculation"]["metrics"]["nitrogen_boundary_tg_per_year"])
        self.assertIs(payload["needs_human_decision"], True)
        self.assertIs(payload["ok"], False)


class VersionTests(PersistenceTestCase):
    def test_major_mismatch_rejected_naming_both_versions(self):
        target = _craft_envelope(self._path(), schema_version="2.0.0")
        with self.assertRaises(ValueError) as ctx:
            load_envelope(target)
        message = str(ctx.exception)
        self.assertIn("2.0.0", message)
        self.assertIn(SCHEMA_VERSION, message)
        self.assertIn(str(target), message)

    def test_same_major_minor_accepted(self):
        target = _craft_envelope(self._path(), schema_version="1.5.0")
        loaded = load_envelope(target)
        self.assertEqual(loaded["schema_version"], "1.5.0")
        self.assertEqual(loaded["payload"], NITROGEN_ONLY_RESULT)

    def test_same_major_patch_accepted(self):
        target = _craft_envelope(self._path(), schema_version="1.0.1")
        loaded = load_envelope(target)
        self.assertEqual(loaded["schema_version"], "1.0.1")

    def test_major_zero_rejected(self):
        target = _craft_envelope(self._path(), schema_version="0.9.0")
        with self.assertRaises(ValueError):
            load_envelope(target)

    def test_malformed_version_rejected(self):
        for bad in ("banana", "1.0", "1.0.0.0", 1, None):
            with self.subTest(bad=bad):
                target = _craft_envelope(self._path(), schema_version=bad)
                with self.assertRaises(ValueError):
                    load_envelope(target)


class LoadFailureTests(PersistenceTestCase):
    def test_corrupt_json_raises_value_error_naming_path(self):
        target = self._path()
        target.write_text("{not json", encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            load_envelope(target)
        self.assertIn(str(target), str(ctx.exception))

    def test_missing_file_raises_value_error_not_filenotfound(self):
        target = self._path("absent.json")
        with self.assertRaises(ValueError) as ctx:
            load_envelope(target)
        self.assertIn(str(target), str(ctx.exception))

    def test_non_object_top_level_rejected(self):
        target = self._path()
        target.write_text("[1, 2, 3]", encoding="utf-8")
        with self.assertRaises(ValueError):
            load_envelope(target)

    def test_missing_envelope_key_rejected(self):
        for key in ("schema_version", "kind", "saved_at", "payload"):
            with self.subTest(missing=key):
                target = _craft_envelope(self._path(), omit=(key,))
                with self.assertRaises(ValueError) as ctx:
                    load_envelope(target)
                self.assertIn(key, str(ctx.exception))

    def test_unknown_kind_on_load_rejected_naming_kind(self):
        target = _craft_envelope(self._path(), kind="teleport")
        with self.assertRaises(ValueError) as ctx:
            load_envelope(target)
        self.assertIn("teleport", str(ctx.exception))

    def test_saved_at_must_be_a_non_empty_string(self):
        target = _craft_envelope(self._path())
        raw = json.loads(target.read_text(encoding="utf-8"))
        raw["saved_at"] = ""
        target.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaises(ValueError):
            load_envelope(target)


class PayloadShapeTests(PersistenceTestCase):
    def test_result_payload_requires_domain_str_and_calculation_dict(self):
        for bad_payload in (
            {"calculation": {}},                       # no domain
            {"domain": "nutrients"},                   # no calculation
            {"domain": 7, "calculation": {}},          # domain not str
            {"domain": "nutrients", "calculation": []},  # calculation not dict
        ):
            with self.subTest(bad=bad_payload):
                target = _craft_envelope(self._path(), kind="result",
                                         payload=bad_payload)
                with self.assertRaises(ValueError):
                    load_envelope(target)

    def test_scenario_payload_requires_non_empty_id_and_name(self):
        for bad_payload in (
            {"name": "x"},                              # no scenario_id
            {"scenario_id": "s1"},                      # no name
            {"scenario_id": "   ", "name": "x"},        # blank id
            {"scenario_id": "s1", "name": ""},          # blank name
            {"scenario_id": 7, "name": "x"},            # id not str
        ):
            with self.subTest(bad=bad_payload):
                target = _craft_envelope(self._path(), kind="scenario",
                                         payload=bad_payload)
                with self.assertRaises(ValueError):
                    load_envelope(target)

    def test_plan_request_and_overrides_need_only_a_dict_payload(self):
        for kind in ("plan_request", "plan_overrides"):
            with self.subTest(kind=kind):
                target = _craft_envelope(self._path(), kind=kind, payload={})
                self.assertEqual(load_envelope(target)["payload"], {})
                target = _craft_envelope(self._path(), kind=kind, payload=[1])
                with self.assertRaises(ValueError):
                    load_envelope(target)


class AtomicityTests(PersistenceTestCase):
    def test_failed_replace_leaves_no_target_file(self):
        target = self._path()
        with mock.patch("os.replace",
                        side_effect=OSError("simulated crash")):
            with self.assertRaises(OSError):
                save_envelope(target, "result", NITROGEN_ONLY_RESULT)
        self.assertFalse(target.exists())
        # No orphaned temp file left behind in the directory either.
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_refused_overwrite_leaves_old_file_byte_identical(self):
        target = self._path()
        save_envelope(target, "result", NITROGEN_ONLY_RESULT)
        before = target.read_bytes()
        with self.assertRaises(FileExistsError) as ctx:
            save_envelope(target, "result", PLAN_REQUEST)
        self.assertIn(str(target), str(ctx.exception))
        self.assertEqual(target.read_bytes(), before)
        # The old payload is still the one that loads.
        self.assertEqual(load_envelope(target)["payload"], NITROGEN_ONLY_RESULT)

    def test_overwrite_true_replaces_the_file(self):
        target = self._path()
        save_envelope(target, "plan_request", PLAN_REQUEST)
        save_envelope(target, "plan_request",
                      {"phosphorus_application_tg_per_year": 6.0},
                      overwrite=True)
        loaded = load_envelope(target)
        self.assertEqual(loaded["payload"],
                         {"phosphorus_application_tg_per_year": 6.0})


class LoggingTests(PersistenceTestCase):
    def test_save_and_load_emit_info_events_with_metadata_only(self):
        target = self._path()
        with self.assertLogs("start.persistence", level="INFO") as logs:
            save_envelope(target, "result", NITROGEN_ONLY_RESULT)
            load_envelope(target)
        records = logs.records
        self.assertEqual([r.event for r in records], ["save", "load"])
        for record in records:
            self.assertEqual(record.levelno, logging.INFO)
            self.assertEqual(record.fields["kind"], "result")
            self.assertEqual(record.fields["path"], str(target))
            self.assertEqual(record.fields["schema_version"], SCHEMA_VERSION)
            # Metadata only: no payload content anywhere in the record.
            self.assertNotIn("nitrogen", str(record.fields))
            self.assertNotIn("165.0", str(record.fields))

    def test_failed_save_logs_a_warning_without_payload(self):
        with self.assertLogs("start.persistence", level="WARNING") as logs:
            with self.assertRaises(ValueError):
                save_envelope(self._path(), "nope", {})
        record = logs.records[0]
        self.assertEqual(record.event, "save_failed")
        self.assertEqual(record.levelno, logging.WARNING)
        self.assertIn("reason", record.fields)


if __name__ == "__main__":
    unittest.main()
