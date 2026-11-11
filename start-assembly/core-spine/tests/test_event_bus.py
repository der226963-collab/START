"""Monitoring event-bus tests (Beam-Telemetry event-bus rebuild).

Run from core-spine/ with:
    .venv/bin/python -m unittest discover -s tests -v
Synthetic data only (adapters.event_bus.synthetic_bus and
make_event): no network, no real telemetry backend. Never claim
a test passed unless it ran here.
"""

import copy
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from adapters import event_bus  # noqa: E402
from adapters.event_bus import EventBus, make_event  # noqa: E402


def _candidate_event(verified=False):
    return make_event(
        "plan.candidate",
        {"delivered_t": 600, "shortage_t": 50, "demand_t": 650},
        licence="Apache-2.0",
        provenance="synthetic test case — START original",
        verified=verified)


class TestAttachDetach(unittest.TestCase):
    def test_attached_handler_receives_events(self):
        bus = EventBus()
        seen = []
        bus.attach("plan.candidate", lambda e: seen.append(e["event"]))
        bus.execute("plan.candidate", _candidate_event())
        self.assertEqual(seen, ["plan.candidate"])

    def test_detached_handler_receives_nothing(self):
        bus = EventBus()
        seen = []

        def handler(event):
            seen.append(event["event"])

        bus.attach("plan.candidate", handler)
        bus.execute("plan.candidate", _candidate_event())
        self.assertEqual(len(seen), 1)
        self.assertTrue(bus.detach("plan.candidate", handler))
        bus.execute("plan.candidate", _candidate_event())
        self.assertEqual(len(seen), 1)  # nothing more after detach
        self.assertEqual(bus.attached("plan.candidate"), [])

    def test_detach_never_attached_is_safe_noop(self):
        # Chosen behaviour: safe no-op returning False, never an
        # error — teardown / re-registration code cannot fail on
        # a handler that was already gone.
        bus = EventBus()
        self.assertFalse(bus.detach("plan.candidate", lambda e: None))
        bus.attach("plan.candidate", lambda e: None)
        other = lambda e: None  # noqa: E731 — a different handler
        self.assertFalse(bus.detach("plan.candidate", other))
        self.assertFalse(bus.detach("no.such.event", other))

    def test_attach_is_idempotent(self):
        bus = EventBus()
        calls = []

        def handler(event):
            calls.append(event["event"])

        self.assertTrue(bus.attach("plan.candidate", handler))
        self.assertFalse(bus.attach("plan.candidate", handler))
        bus.execute("plan.candidate", _candidate_event())
        self.assertEqual(calls, ["plan.candidate"])  # called once

    def test_handlers_run_in_attach_order(self):
        bus = EventBus()
        order = []
        bus.attach("plan.candidate", lambda e: order.append("first"))
        bus.attach("plan.candidate", lambda e: order.append("second"))
        bus.attach("plan.candidate", lambda e: order.append("third"))
        bus.execute("plan.candidate", _candidate_event())
        self.assertEqual(order, ["first", "second", "third"])


class TestVerifiedFlag(unittest.TestCase):
    def test_unverified_event_arrives_unverified(self):
        bus = EventBus()
        seen = []
        bus.attach("plan.candidate",
                   lambda e: seen.append(copy.deepcopy(e)))
        record = bus.execute("plan.candidate", _candidate_event())
        self.assertFalse(seen[0]["verified"])
        self.assertFalse(record["verified"])
        self.assertFalse(record["event_dispatched"]["verified"])
        self.assertTrue(record["needs_human_decision"])
        self.assertEqual(len(bus.log()), 1)
        self.assertFalse(bus.log()[0]["verified"])
        self.assertEqual(bus.log()[0]["outcome"], "accepted")

    def test_verified_flag_carried_not_invented(self):
        # A stored verified=true is carried unchanged through
        # dispatch and the log — the bus never invents it, and
        # never clears it either; it only ever carries it.
        bus = EventBus()
        seen = []
        bus.attach("plan.candidate",
                   lambda e: seen.append(copy.deepcopy(e)))
        record = bus.execute("plan.candidate",
                             _candidate_event(verified=True))
        self.assertTrue(seen[0]["verified"])
        self.assertTrue(record["verified"])
        self.assertTrue(bus.log()[0]["verified"])
        self.assertEqual(bus.log()[0]["outcome"], "accepted")


class TestPromotionRejected(unittest.TestCase):
    def test_promotion_by_return_value_is_rejected(self):
        bus = EventBus()

        def promoter(event):
            promoted = dict(event)
            promoted["verified"] = True
            return promoted

        seen = []
        bus.attach("plan.candidate", promoter)
        bus.attach("plan.candidate",
                   lambda e: seen.append(copy.deepcopy(e)))
        record = bus.execute("plan.candidate", _candidate_event())
        # The promotion did not take effect anywhere observable.
        self.assertFalse(record["verified"])
        self.assertFalse(record["event_dispatched"]["verified"])
        self.assertFalse(seen[0]["verified"])  # downstream consumer
        entries = bus.log()
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["outcome"], "rejected")
        self.assertFalse(entries[0]["verified"])
        self.assertIn("verified", entries[0]["detail"])
        self.assertEqual(entries[1]["outcome"], "accepted")

    def test_promotion_by_mutation_is_rejected(self):
        bus = EventBus()

        def mutator(event):
            event["verified"] = True  # mutates only its own copy

        seen = []
        bus.attach("plan.candidate", mutator)
        bus.attach("plan.candidate",
                   lambda e: seen.append(copy.deepcopy(e)))
        record = bus.execute("plan.candidate", _candidate_event())
        self.assertFalse(record["verified"])
        self.assertFalse(record["event_dispatched"]["verified"])
        self.assertFalse(seen[0]["verified"])  # later handler unaffected
        entries = bus.log()
        self.assertEqual(entries[0]["outcome"], "rejected")
        self.assertFalse(entries[0]["verified"])
        self.assertIn("mutated", entries[0]["detail"])
        # The bus's stored copy was never touched: a second
        # dispatch of the same event object still sees false.
        record2 = bus.execute("plan.candidate", _candidate_event())
        self.assertFalse(record2["event_dispatched"]["verified"])

    def test_demotion_is_rejected_too(self):
        # Handlers never change the flag in either direction:
        # demoting a verified event is rejected just like
        # promoting an unverified one.
        bus = EventBus()

        def demoter(event):
            demoted = dict(event)
            demoted["verified"] = False
            return demoted

        bus.attach("plan.candidate", demoter)
        record = bus.execute("plan.candidate",
                             _candidate_event(verified=True))
        self.assertTrue(record["verified"])
        self.assertEqual(bus.log()[0]["outcome"], "rejected")


class TestProvenanceAndWireFormat(unittest.TestCase):
    def test_provenance_survives_round_trip(self):
        bus = EventBus()
        seen = []
        bus.attach("plan.candidate",
                   lambda e: seen.append(copy.deepcopy(e)))
        event = _candidate_event()
        record = bus.execute("plan.candidate", event)
        # Licence/provenance on the event the handler saw, on the
        # dispatch record, and in the log are the ones that went in.
        self.assertEqual(seen[0]["licence"], "Apache-2.0")
        self.assertEqual(seen[0]["provenance"],
                         "synthetic test case — START original")
        self.assertEqual(record["licence"], "Apache-2.0")
        self.assertEqual(record["provenance"],
                         "synthetic test case — START original")
        self.assertEqual(record["event_dispatched"]["licence"],
                         event["licence"])
        self.assertEqual(record["event_dispatched"]["provenance"],
                         event["provenance"])
        self.assertEqual(record["event_dispatched"]["payload"],
                         event["payload"])
        # The caller's own event object was not modified by dispatch.
        self.assertFalse(event["verified"])
        self.assertEqual(event["payload"]["delivered_t"], 600)

    def test_dispatch_record_json_round_trip(self):
        bus = EventBus()
        bus.attach("plan.candidate", lambda e: None)
        record = bus.execute("plan.candidate", _candidate_event())
        text = event_bus.dispatch_record_to_json(record)
        json.loads(text)  # must be plain JSON
        restored = event_bus.dispatch_record_from_json(text)
        self.assertEqual(restored["verified"], False)
        self.assertEqual(restored["licence"], "Apache-2.0")
        self.assertEqual(restored["results"][0]["outcome"], "accepted")
        log_text = bus.log_to_json()
        json.loads(log_text)
        self.assertEqual(json.loads(log_text)[0]["verified"], False)


class TestHandlerErrors(unittest.TestCase):
    def test_raising_handler_is_logged_and_dispatch_continues(self):
        bus = EventBus()
        ran = []

        def raiser(event):
            raise RuntimeError("boom in handler")

        bus.attach("plan.candidate", raiser)
        bus.attach("plan.candidate", lambda e: ran.append("second"))
        bus.attach("plan.candidate", lambda e: ran.append("third"))
        record = bus.execute("plan.candidate", _candidate_event())
        self.assertEqual(ran, ["second", "third"])  # later handlers ran
        self.assertEqual(record["handlers_run"], 3)
        entries = bus.log()
        self.assertEqual(entries[0]["outcome"], "error")
        self.assertIn("RuntimeError", entries[0]["detail"])
        self.assertIn("boom in handler", entries[0]["detail"])
        self.assertEqual(entries[1]["outcome"], "accepted")
        self.assertEqual(entries[2]["outcome"], "accepted")
        # The event was not lost: the dispatch record still
        # carries it, verified=false as dispatched.
        self.assertFalse(record["event_dispatched"]["verified"])
        self.assertEqual(record["status"], "ok")


class TestExecuteValidation(unittest.TestCase):
    def test_event_name_mismatch_rejected(self):
        bus = EventBus()
        bus.attach("plan.candidate", lambda e: None)
        with self.assertRaises(ValueError):
            bus.execute("plan.verified", _candidate_event())
        self.assertEqual(bus.log(), [])  # nothing dispatched

    def test_missing_field_rejected(self):
        bus = EventBus()
        event = _candidate_event()
        del event["licence"]
        with self.assertRaises(ValueError):
            bus.execute("plan.candidate", event)

    def test_execute_with_no_handlers_is_ok(self):
        bus = EventBus()
        record = bus.execute("plan.candidate", _candidate_event())
        self.assertEqual(record["status"], "ok")
        self.assertEqual(record["handlers_run"], 0)
        self.assertEqual(record["results"], [])
        self.assertEqual(bus.log(), [])


class TestSyntheticBus(unittest.TestCase):
    def test_synthetic_bus_logging_and_metrics(self):
        bus, seen, counts = event_bus.synthetic_bus()
        bus.execute("plan.candidate", _candidate_event())
        bus.execute("plan.verified",
                    make_event("plan.verified",
                               {"delivered_t": 600, "shortage_t": 50},
                               verified=False))
        self.assertEqual(len(seen), 2)
        self.assertEqual(counts, {"plan.candidate": 1,
                                  "plan.verified": 1})
        self.assertTrue(all(not e["verified"] for e in seen))


if __name__ == "__main__":
    unittest.main()
