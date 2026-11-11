"""RAP hibernation-pattern tests (hydro-project/infinity rebuild).

Run from core-spine/ with:
    .venv/bin/python -m unittest discover -s tests -v
Synthetic data only (adapters.hibernation.synthetic_*): no
network, no listener, no callback URL, no Infinity code.
Never claim a test passed unless it ran here.
"""

import hashlib
import json
import os
import unittest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from adapters import hibernation as hb  # noqa: E402


def _hibernate_wake(session):
    """Hibernate a session and wake it back, returning the woken session."""
    return hb.wake(hb.hibernate(session))


class TestInvokeAck(unittest.TestCase):
    def test_invoke_returns_immediate_ack_and_no_result(self):
        session, ack = hb.invoke_tool(
            "s1", "call-1", "solve_food_lp", {"demand_t": 650},
            subscriptions=("planner",))
        self.assertEqual(session["state"], "ACTIVE")
        self.assertIs(session["result"], None)
        self.assertEqual(session["subscriptions"], ["planner"])
        self.assertIs(session["verified"], False)
        self.assertTrue(session["needs_human_decision"])
        self.assertIs(ack["acknowledged"], True)
        self.assertEqual(ack["session_id"], "s1")
        self.assertEqual(ack["tool_call_id"], "call-1")
        self.assertEqual(ack["state"], "ACTIVE")
        self.assertIs(ack["verified"], False)
        self.assertTrue(ack["needs_human_decision"])
        json.dumps(session)
        json.dumps(ack)

    def test_synthetic_session_is_the_food_lp_invocation(self):
        session = hb.synthetic_session()
        self.assertEqual(session["session_id"],
                         "synthetic-food-lp-session")
        self.assertEqual(session["tool_call_id"], "call-food-lp-001")
        self.assertEqual(session["tool_name"], "solve_food_lp")
        self.assertEqual(session["tool_args"]["demand_t"], 650)
        self.assertEqual(session["subscriptions"],
                         ["planner", "verifier"])
        self.assertEqual(session["state"], "ACTIVE")
        self.assertIs(session["result"], None)

    def test_bad_invoke_arguments_are_rejected(self):
        with self.assertRaises(ValueError):
            hb.invoke_tool("", "call-1", "tool", {})
        with self.assertRaises(ValueError):
            hb.invoke_tool("s1", "  ", "tool", {})
        with self.assertRaises(ValueError):
            hb.invoke_tool("s1", "call-1", "tool", {1, 2, 3})
        with self.assertRaises(ValueError):
            hb.invoke_tool("s1", "call-1", "tool", {},
                           subscriptions="planner")
        # Duplicate subscriptions are dropped, order kept.
        session, _ = hb.invoke_tool("s1", "call-1", "tool", {},
                                    subscriptions=("a", "b", "a"))
        self.assertEqual(session["subscriptions"], ["a", "b"])


class TestHibernateWakeRoundTrip(unittest.TestCase):
    def test_hibernate_wake_hibernate_is_byte_identical(self):
        session = hb.synthetic_session()
        first = hb.hibernate(session)
        self.assertEqual(session["state"], "HIBERNATING")
        woken = hb.wake(first)
        self.assertEqual(woken["state"], "WOKEN")
        self.assertEqual(woken["session_id"], "synthetic-food-lp-session")
        self.assertEqual(woken["tool_args"]["demand_t"], 650)
        second = hb.hibernate(woken)
        self.assertEqual(second, first)
        # And a third cycle is identical too.
        self.assertEqual(hb.hibernate(hb.wake(second)), first)
        json.loads(first)

    def test_hibernate_wake_preserves_subscriptions_and_result(self):
        session = hb.synthetic_session()
        hb.subscribe(session, "auditor")
        hb.deliver_result(session, hb.synthetic_result_payload(), "PASS")
        first = hb.hibernate(session)
        woken = hb.wake(first)
        self.assertEqual(woken["subscriptions"],
                         ["planner", "verifier", "auditor"])
        self.assertEqual(woken["result"]["payload"],
                         hb.synthetic_result_payload())
        self.assertEqual(woken["result"]["status"], "PASS")
        self.assertEqual(hb.hibernate(woken), first)

    def test_invalid_state_transitions_raise(self):
        session = hb.synthetic_session()
        text = hb.hibernate(session)
        # Already hibernating: cannot hibernate again.
        with self.assertRaises(ValueError):
            hb.hibernate(session)
        # Waking a non-hibernating payload: craft one in ACTIVE.
        active, _ = hb.invoke_tool("s2", "call-2", "tool", {})
        payload = {k: v for k, v in active.items()}
        payload["checksum"] = hb._checksum(payload)
        with self.assertRaises(ValueError):
            hb.wake(hb._canonical(payload))
        # Waking twice from the same string: the second wake sees
        # a WOKEN state only if re-serialised; the raw string wakes
        # fine a second time (it is still HIBERNATING on disk),
        # so instead check a non-string and non-JSON input.
        with self.assertRaises(ValueError):
            hb.wake(123)
        with self.assertRaises(ValueError):
            hb.wake("not json {")
        with self.assertRaises(ValueError):
            hb.wake(json.dumps({"schema_version": "1.0.0"}))
        # The valid string still wakes after the failed attempts.
        self.assertEqual(hb.wake(text)["state"], "WOKEN")

    def test_tampered_hibernated_state_is_rejected(self):
        session = hb.synthetic_session()
        text = hb.hibernate(session)
        envelope = json.loads(text)
        envelope["tool_args"] = {"demand_t": 1}
        tampered = json.dumps(envelope, sort_keys=True,
                              separators=(",", ":"))
        with self.assertRaises(ValueError):
            hb.wake(tampered)
        # Flipping one character of the checksum also fails.
        envelope = json.loads(text)
        envelope["checksum"] = ("0" if envelope["checksum"][0] != "0"
                                else "1") + envelope["checksum"][1:]
        with self.assertRaises(ValueError):
            hb.wake(json.dumps(envelope, sort_keys=True,
                               separators=(",", ":")))
        # Wrong schema version fails even with a fresh checksum.
        envelope = json.loads(text)
        envelope["schema_version"] = "2.0.0"
        payload = {k: v for k, v in envelope.items() if k != "checksum"}
        envelope["checksum"] = hb._checksum(payload)
        with self.assertRaises(ValueError):
            hb.wake(json.dumps(envelope, sort_keys=True,
                               separators=(",", ":")))


class TestResultAfterHibernation(unittest.TestCase):
    def test_result_delivered_after_hibernation_is_held_unverified(self):
        session = hb.synthetic_session()
        woken = _hibernate_wake(session)
        hb.deliver_result(woken, hb.synthetic_result_payload(), "PASS")
        result = woken["result"]
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["payload"]["delivered_t"], 600)
        self.assertEqual(result["payload"]["shortage_t"], 50)
        self.assertIs(result["verified"], False)
        self.assertTrue(result["needs_human_decision"])
        self.assertIs(woken["verified"], False)
        json.dumps(woken)

    def test_verify_pass_with_human_approval_verifies(self):
        woken = _hibernate_wake(hb.synthetic_session())
        hb.deliver_result(woken, hb.synthetic_result_payload(), "PASS")
        record = hb.verify_result(woken, "PASS", True)
        self.assertIs(record["verified"], True)
        self.assertIs(record["human_approved"], True)
        self.assertEqual(record["verdict"], "PASS")
        self.assertIs(woken["verified"], True)
        self.assertIs(woken["result"]["verified"], True)
        self.assertTrue(record["needs_human_decision"])
        json.dumps(record)

    def test_verify_pass_without_human_approval_does_not_verify(self):
        woken = _hibernate_wake(hb.synthetic_session())
        hb.deliver_result(woken, hb.synthetic_result_payload(), "PASS")
        record = hb.verify_result(woken, "PASS", False)
        self.assertIs(record["verified"], False)
        self.assertIs(woken["verified"], False)
        self.assertIs(woken["result"]["verified"], False)

    def test_verify_fail_never_verifies_even_with_approval(self):
        woken = _hibernate_wake(hb.synthetic_session())
        hb.deliver_result(woken, {"delivered_t": 400}, "FAIL")
        record = hb.verify_result(woken, "FAIL", True)
        self.assertIs(record["verified"], False)
        self.assertIs(woken["verified"], False)
        unknown = _hibernate_wake(hb.synthetic_session())
        hb.deliver_result(unknown, {}, "UNKNOWN")
        self.assertIs(hb.verify_result(unknown, "UNKNOWN", True)
                      ["verified"], False)

    def test_delivery_rules(self):
        woken = _hibernate_wake(hb.synthetic_session())
        with self.assertRaises(ValueError):
            hb.deliver_result(woken, {}, "MAYBE")
        with self.assertRaises(ValueError):
            hb.deliver_result(woken, {1, 2}, "PASS")
        hb.deliver_result(woken, hb.synthetic_result_payload(), "PASS")
        # A second delivery is a protocol error, not an update.
        with self.assertRaises(ValueError):
            hb.deliver_result(woken, {}, "FAIL")
        # No verify without a delivered result.
        fresh = _hibernate_wake(hb.synthetic_session())
        with self.assertRaises(ValueError):
            hb.verify_result(fresh, "PASS", True)
        with self.assertRaises(ValueError):
            hb.verify_result(fresh, "MAYBE", True)
        # No delivery or verify while hibernating.
        session = hb.synthetic_session()
        hb.hibernate(session)
        with self.assertRaises(ValueError):
            hb.deliver_result(session, {}, "PASS")
        with self.assertRaises(ValueError):
            hb.verify_result(session, "PASS", True)


class TestSubscriptionsPersist(unittest.TestCase):
    def test_subscriptions_survive_two_hibernations(self):
        session = hb.synthetic_session()
        hb.subscribe(session, "auditor")
        hb.unsubscribe(session, "verifier")
        first = hb.hibernate(session)
        woken = hb.wake(first)
        self.assertEqual(woken["subscriptions"],
                         ["planner", "auditor"])
        second = hb.hibernate(woken)
        self.assertEqual(second, first)
        self.assertEqual(hb.wake(second)["subscriptions"],
                         ["planner", "auditor"])

    def test_subscribe_rules(self):
        session = hb.synthetic_session()
        hb.subscribe(session, "planner")  # duplicate: no-op
        self.assertEqual(session["subscriptions"],
                         ["planner", "verifier"])
        hb.unsubscribe(session, "nobody")  # absent: no-op
        self.assertEqual(session["subscriptions"],
                         ["planner", "verifier"])
        with self.assertRaises(ValueError):
            hb.subscribe(session, "")
        hb.hibernate(session)
        with self.assertRaises(ValueError):
            hb.subscribe(session, "auditor")
        with self.assertRaises(ValueError):
            hb.unsubscribe(session, "planner")


class TestNeverWakesVerified(unittest.TestCase):
    def test_hibernated_state_never_wakes_verified(self):
        session = hb.synthetic_session()
        hb.deliver_result(session, hb.synthetic_result_payload(), "PASS")
        hb.verify_result(session, "PASS", True)
        self.assertIs(session["verified"], True)
        # Hibernating forces it back to unverified, and waking
        # does not restore it: verification does not survive
        # hibernation and must be re-done after waking.
        woken = hb.wake(hb.hibernate(session))
        self.assertIs(woken["verified"], False)
        self.assertIs(woken["result"]["verified"], False)
        self.assertTrue(woken["needs_human_decision"])

    def test_hand_crafted_verified_payload_wakes_unverified(self):
        session = hb.synthetic_session()
        text = hb.hibernate(session)
        envelope = json.loads(text)
        # Hand-craft a persisted state claiming verified, with a
        # valid checksum (as a tampered store would): wake must
        # still force it to False, not trust the stored flag.
        envelope["verified"] = True
        envelope["result"] = {
            "schema_version": "1.0.0", "status": "PASS",
            "payload": hb.synthetic_result_payload(),
            "verified": True, "needs_human_decision": True}
        payload = {k: v for k, v in envelope.items() if k != "checksum"}
        envelope["checksum"] = hashlib.sha256(
            json.dumps(payload, sort_keys=True,
                       separators=(",", ":")).encode("utf-8")).hexdigest()
        woken = hb.wake(json.dumps(envelope, sort_keys=True,
                                   separators=(",", ":")))
        self.assertIs(woken["verified"], False)
        self.assertIs(woken["result"]["verified"], False)

    def test_verified_result_rehibernated_wakes_unverified(self):
        woken = _hibernate_wake(hb.synthetic_session())
        hb.deliver_result(woken, hb.synthetic_result_payload(), "PASS")
        hb.verify_result(woken, "PASS", True)
        self.assertIs(woken["verified"], True)
        rewoken = hb.wake(hb.hibernate(woken))
        self.assertIs(rewoken["verified"], False)
        self.assertIs(rewoken["result"]["verified"], False)
        # It can be re-verified after waking, by the verify step.
        self.assertIs(
            hb.verify_result(rewoken, "PASS", True)["verified"], True)


class TestLocalOnlyNoCallback(unittest.TestCase):
    def test_register_callback_is_always_rejected(self):
        with self.assertRaises(ValueError):
            hb.register_callback("https://example.com/callback")
        with self.assertRaises(ValueError):
            hb.register_callback("https://example.com/callback",
                                 auth_token="secret-token")
        with self.assertRaises(ValueError):
            hb.register_callback("http://localhost:8080/hook")

    def test_no_callback_url_anywhere_in_a_session(self):
        session = hb.synthetic_session()
        text = hb.hibernate(session)
        self.assertNotIn("callback", text.lower())
        self.assertNotIn("http", text.lower())
        woken = hb.wake(text)
        self.assertNotIn("callback_url", woken)
        self.assertNotIn("callback", json.dumps(woken).lower())


class TestSourcePin(unittest.TestCase):
    def test_module_source_is_local_only_and_never_sets_verified(self):
        here = os.path.dirname(__file__)
        path = os.path.join(here, "..", "adapters", "hibernation.py")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        # No network, no listener, no Infinity code or dependency:
        # check the code below the module docstring (the docstring
        # itself names the refused crate to explain the refusal).
        code = source.split('"""\n\nimport hashlib', 1)[1]
        self.assertNotIn("rap-protocol", code)
        self.assertNotIn("rap_protocol", code)
        self.assertNotIn("RapInvocation", code)
        self.assertNotIn("RapCallback", code)
        self.assertNotIn("import socket", source)
        self.assertNotIn("import http", source)
        self.assertNotIn("import requests", source)
        self.assertNotIn("import urllib", source)
        # The verified flag is only ever forced False or set from
        # the single verify expression — never written True.
        self.assertNotIn("verified=True", source)
        self.assertNotIn("verified = True", source)
        self.assertNotIn('"verified": True', source)
        self.assertIn('verified = (verdict == "PASS" and '
                      'human_approved is True)', source)
        self.assertIn("register_callback", source)
        self.assertIn("local-only", source)


if __name__ == "__main__":
    unittest.main()
