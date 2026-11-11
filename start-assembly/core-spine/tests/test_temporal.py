"""Temporal knowledge tests (Graphiti temporal-schema rebuild).

Run from core-spine/ with:
    .venv/bin/python -m unittest discover -s tests -v
Synthetic data only (adapters.temporal.synthetic_store): a small
food-system knowledge timeline. No real data, no graph database,
no LLM. Never claim a test passed unless it ran here.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from adapters import temporal  # noqa: E402
from adapters.temporal import Episode, TemporalStore  # noqa: E402


class TestTemporalSupersession(unittest.TestCase):
    def test_superseded_never_current_now(self):
        # "Now" (2026-11-11): wheat-b is current; wheat-a is
        # superseded and must not appear, even though its window
        # would otherwise still be open-ended in the old record.
        store = temporal.synthetic_store()
        ids = [ep.id for ep in store.current("2026-11-11")]
        self.assertIn("ep-wheat-2026b", ids)
        self.assertNotIn("ep-wheat-2026a", ids)

    def test_superseded_never_current_inside_old_window(self):
        # 2026-03-01 is inside wheat-a's ORIGINAL window
        # (2026-01-01..2026-06-30), but wheat-a is superseded by
        # wheat-b, so it is never returned as current — and wheat-b
        # is not yet valid, so no wheat episode is current at all.
        store = temporal.synthetic_store()
        ids = [ep.id for ep in store.current("2026-03-01")]
        self.assertNotIn("ep-wheat-2026a", ids)
        self.assertNotIn("ep-wheat-2026b", ids)

    def test_superseded_by_points_at_replacer(self):
        store = temporal.synthetic_store()
        old = store.get("ep-wheat-2026a")
        self.assertEqual(old.superseded_by, "ep-wheat-2026b")
        self.assertIsNotNone(store.get(old.superseded_by))

    def test_follow_chain_reaches_current(self):
        store = TemporalStore()
        store.add(Episode("c1", "fact v1", "2026-01-01", "2026-03-31",
                          superseded_by="c2", links={"next": "c2"}))
        store.add(Episode("c2", "fact v2", "2026-04-01", "2026-06-30",
                          superseded_by="c3", links={"previous": "c1",
                                                     "next": "c3"}))
        store.add(Episode("c3", "fact v3", "2026-07-01", None,
                          links={"previous": "c2"}))
        episode, status, _reason = store.follow_chain("c1")
        self.assertEqual(status, "current")
        self.assertEqual(episode.id, "c3")
        self.assertTrue(episode.is_current("2026-11-11"))


class TestTemporalFiltering(unittest.TestCase):
    def test_valid_window_filtering_t1_t2(self):
        store = temporal.synthetic_store()
        at_t1 = [ep.id for ep in store.current("2026-06-01")]
        at_t2 = [ep.id for ep in store.current("2027-06-01")]
        self.assertIn("ep-water-2026", at_t1)
        self.assertNotIn("ep-water-2027", at_t1)
        self.assertIn("ep-water-2027", at_t2)
        self.assertNotIn("ep-water-2026", at_t2)

    def test_query_outside_all_windows_returns_empty(self):
        # Not an error, not a stale record: an empty list.
        store = temporal.synthetic_store()
        # Before every valid_from in the store.
        self.assertEqual(store.current("2025-06-01"), [])
        result = temporal.query_current(store, "2025-06-01")
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["episodes"], [])
        self.assertEqual(result["status"], "ok")
        # After every BOUNDED window: a store with only the two
        # water episodes (both closed windows) is empty at 2028.
        bounded = TemporalStore()
        bounded.add(Episode("w26", "Water 2026", "2026-01-01",
                            "2026-12-31"))
        bounded.add(Episode("w27", "Water 2027", "2027-01-01",
                            "2027-12-31"))
        self.assertEqual(bounded.current("2028-06-01"), [])
        self.assertEqual(
            temporal.query_current(bounded, "2028-06-01")["count"], 0)

    def test_query_empty_store_returns_empty(self):
        self.assertEqual(TemporalStore().current("2026-06-01"), [])

    def test_window_boundaries_inclusive(self):
        store = temporal.synthetic_store()
        self.assertIn("ep-water-2026",
                      [ep.id for ep in store.current("2026-01-01")])
        self.assertIn("ep-water-2026",
                      [ep.id for ep in store.current("2026-12-31")])
        # Day after valid_to: no longer current.
        self.assertNotIn("ep-water-2026",
                         [ep.id for ep in store.current("2027-01-01")])

    def test_open_ended_valid_to_is_current(self):
        store = temporal.synthetic_store()
        self.assertIn("ep-wheat-2026b",
                      [ep.id for ep in store.current("2030-01-01")])


class TestTemporalVerified(unittest.TestCase):
    def test_superseded_verified_excluded_from_current(self):
        # ep-potato-old was stored with verified=true BEFORE it was
        # superseded. It must still never appear in current results.
        store = temporal.synthetic_store()
        self.assertTrue(store.get("ep-potato-old").verified)
        ids = [ep.id for ep in store.current("2026-06-01")]
        self.assertNotIn("ep-potato-old", ids)
        self.assertIn("ep-potato-new", ids)

    def test_current_verified_query_excludes_superseded(self):
        store = temporal.synthetic_store()
        # The only stored-verified episode is superseded, and the
        # current potato episode is unverified: current-verified
        # is empty at every queried time.
        for at in ("2026-06-01", "2026-11-11", "2027-06-01"):
            ids = [ep.id for ep in store.current_verified(at)]
            self.assertNotIn("ep-potato-old", ids)
            self.assertEqual(ids, [])

    def test_temporal_layer_never_sets_verified(self):
        # An unverified episode stays unverified through add,
        # query, supersession and JSON round-trip; nothing in this
        # module can mark it verified (there is no setter API).
        store = TemporalStore()
        store.add(Episode("v1", "unverified fact", "2026-01-01", None,
                          verified=False))
        store.add(Episode("v2", "replacement fact", "2026-07-01", None,
                          verified=False))
        store.supersede("v1", "v2")
        result = temporal.query_current(store, "2026-11-11")
        self.assertFalse(result["episodes"][0]["verified"])
        self.assertFalse(result["verified"])  # the result itself
        self.assertTrue(result["needs_human_decision"])
        restored = temporal.store_from_json(temporal.store_to_json(store))
        self.assertFalse(restored.get("v1").verified)
        self.assertFalse(restored.get("v2").verified)
        # The stored flag is carried, never invented: a stored
        # verified=true survives the round-trip unchanged too.
        flagged = temporal.synthetic_store()
        self.assertTrue(flagged.get("ep-potato-old").verified)
        again = temporal.store_from_json(
            temporal.store_to_json(flagged))
        self.assertTrue(again.get("ep-potato-old").verified)


class TestTemporalLinksAndWireFormat(unittest.TestCase):
    def test_broken_link_reported_unknown(self):
        store = TemporalStore()
        store.add(Episode("b1", "fact", "2026-01-01", None,
                          superseded_by="ep-missing"))
        episode, status, reason = store.follow_chain("b1")
        self.assertEqual(status, "unknown")
        self.assertIsNone(episode)
        self.assertIn("ep-missing", reason)
        # Never silently resolved to a current record: the broken
        # episode itself is not current either (it is superseded).
        self.assertEqual(store.current("2026-06-01"), [])
        broken = store.validate_links()
        self.assertEqual(len(broken), 1)
        self.assertEqual(broken[0]["from"], "b1")
        self.assertEqual(broken[0]["to"], "ep-missing")

    def test_follow_chain_unknown_start(self):
        store = temporal.synthetic_store()
        episode, status, _reason = store.follow_chain("ep-no-such")
        self.assertEqual(status, "unknown")
        self.assertIsNone(episode)

    def test_superseded_cycle_reported_unknown(self):
        store = TemporalStore()
        store.add(Episode("x1", "fact 1", "2026-01-01", None,
                          superseded_by="x2"))
        store.add(Episode("x2", "fact 2", "2026-01-01", None,
                          superseded_by="x1"))
        episode, status, reason = store.follow_chain("x1")
        self.assertEqual(status, "unknown")
        self.assertIsNone(episode)
        self.assertIn("cycle", reason)

    def test_json_round_trip(self):
        store = temporal.synthetic_store()
        text = temporal.store_to_json(store)
        json.loads(text)  # must be plain JSON
        restored = temporal.store_from_json(text)
        self.assertEqual(
            sorted(ep.id for ep in restored.current("2026-11-11")),
            sorted(ep.id for ep in store.current("2026-11-11")))
        ep = restored.get("ep-wheat-2026a")
        self.assertEqual(ep.superseded_by, "ep-wheat-2026b")
        self.assertEqual(ep.links, {"next": "ep-wheat-2026b"})
        self.assertEqual(ep.valid_from.isoformat(), "2026-01-01")
        self.assertEqual(ep.valid_to.isoformat(), "2026-06-30")
        self.assertIsNone(restored.get("ep-wheat-2026b").valid_to)
        # Episode dicts are JSON-able and carry licence/provenance.
        d = ep.to_dict()
        json.dumps(d)
        self.assertEqual(d["schema_version"], "1.0.0")
        self.assertEqual(d["licence"], "Apache-2.0")
        self.assertIn("provenance", d)

    def test_invalid_window_rejected(self):
        with self.assertRaises(ValueError):
            Episode("bad", "fact", "2026-06-30", "2026-01-01")
        with self.assertRaises(ValueError):
            Episode("bad", "fact", "2026-01-01", None,
                    superseded_by="bad")
        store = TemporalStore()
        store.add(Episode("d1", "fact", "2026-01-01", None))
        with self.assertRaises(ValueError):
            store.add(Episode("d1", "fact again", "2026-01-01", None))


if __name__ == "__main__":
    unittest.main()
