"""Mechanism-simulation tests (Collective-Intelligence-Library
pure-transform rebuild, Module 19).

Run from core-spine/ with:
    .venv/bin/python -m unittest discover -s tests -v
Synthetic data only (adapters.mechanism_simulation.synthetic_state
and small hand-built graphs): no network, no JAX, no real data.
Never claim a test passed unless it ran here.
"""

import copy
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from adapters import mechanism_simulation as ms  # noqa: E402
from adapters.mechanism_simulation import (  # noqa: E402
    GraphState,
    Transform,
    aggregate_outcome,
    compile_pipeline,
    compute_shares,
    run_pipeline,
    synthetic_state,
    tally_preferences,
)


def _tie_state():
    """Weighted tie, hand-computed: wheat 2 (a, weight 2),
    rice 2 (b + c, weight 1 each) — winner is "rice", the
    lexicographically smallest of the tied options."""
    return GraphState(
        nodes={
            "a": {"preference": "wheat", "weight": 2},
            "b": {"preference": "rice", "weight": 1},
            "c": {"preference": "rice", "weight": 1},
        },
        edges=[],
        globals_={})


class TestImmutability(unittest.TestCase):
    def test_step_leaves_input_byte_identical(self):
        state = synthetic_state()
        before = state.to_json()
        new_state = tally_preferences(state)
        # The input state object is byte-identical afterwards.
        self.assertEqual(state.to_json(), before)
        # And the step produced a genuinely new state object.
        self.assertIsNot(new_state, state)
        self.assertNotEqual(new_state.to_json(), before)
        self.assertEqual(new_state.globals()["tally"],
                         {"rice": 2, "wheat": 3})
        self.assertEqual(state.globals(), {})  # input has no tally

    def test_pipeline_leaves_input_unchanged(self):
        state = synthetic_state()
        before = state.to_json()
        before_copy = copy.deepcopy(state.to_dict())
        result = run_pipeline(state, ms.plurality_pipeline())
        self.assertEqual(state.to_json(), before)
        self.assertEqual(state.to_dict(), before_copy)
        self.assertEqual(result["state"]["globals"]["outcome"], "wheat")

    def test_caller_mutating_what_it_got_back_changes_nothing(self):
        state = synthetic_state()
        nodes = state.nodes()
        nodes["n1"]["preference"] = "rice"  # mutate the returned copy
        nodes["n1"]["weight"] = 99
        globals_copy = state.globals()
        globals_copy["tally"] = {"rice": 99}
        # The state itself is untouched: a fresh tally still
        # counts wheat 3 / rice 2.
        self.assertEqual(tally_preferences(state).globals()["tally"],
                         {"rice": 2, "wheat": 3})
        self.assertEqual(state.nodes()["n1"],
                         {"preference": "wheat", "weight": 1})

    def test_constructor_deep_copies_its_inputs(self):
        nodes = {"n1": {"preference": "wheat", "weight": 1}}
        state = GraphState(nodes=nodes, edges=[], globals_={})
        nodes["n1"]["preference"] = "rice"  # mutate caller's dict
        self.assertEqual(state.nodes()["n1"]["preference"], "wheat")


class TestDeterminism(unittest.TestCase):
    def test_same_input_twice_same_output(self):
        first = run_pipeline(synthetic_state(),
                             ms.plurality_pipeline())
        second = run_pipeline(synthetic_state(),
                              ms.plurality_pipeline())
        self.assertEqual(ms.result_to_json(first),
                         ms.result_to_json(second))

    def test_tally_is_deterministic_regardless_of_node_order(self):
        nodes_fwd = synthetic_state().nodes()
        nodes_rev = {k: nodes_fwd[k] for k in reversed(list(nodes_fwd))}
        a = tally_preferences(GraphState(nodes=nodes_fwd))
        b = tally_preferences(GraphState(nodes=nodes_rev))
        self.assertEqual(a.to_json(), b.to_json())


class TestHandComputedCases(unittest.TestCase):
    def test_synthetic_five_node_vote(self):
        # Hand-computed: wheat 3, rice 2; shares 0.6 / 0.4;
        # winner wheat.
        result = run_pipeline(synthetic_state(),
                              ms.plurality_pipeline())
        g = result["state"]["globals"]
        self.assertEqual(g["tally"], {"rice": 2, "wheat": 3})
        self.assertEqual(g["shares"], {"rice": 0.4, "wheat": 0.6})
        self.assertEqual(g["outcome"], "wheat")
        self.assertEqual(g["tied"], ["wheat"])
        self.assertEqual(result["steps"],
                         ["tally_preferences", "aggregate_outcome",
                          "compute_shares"])

    def test_weighted_tie_breaks_lexicographically(self):
        result = run_pipeline(_tie_state(), ms.plurality_pipeline())
        g = result["state"]["globals"]
        self.assertEqual(g["tally"], {"rice": 2, "wheat": 2})
        self.assertEqual(g["shares"], {"rice": 0.5, "wheat": 0.5})
        self.assertEqual(g["outcome"], "rice")  # smallest tied name
        self.assertEqual(g["tied"], ["rice", "wheat"])

    def test_empty_graph_has_no_outcome(self):
        result = run_pipeline(GraphState(), ms.plurality_pipeline())
        g = result["state"]["globals"]
        self.assertEqual(g["tally"], {})
        self.assertEqual(g["shares"], {})
        self.assertIsNone(g["outcome"])
        self.assertEqual(g["tied"], [])

    def test_tally_is_idempotent_on_rerun(self):
        state = tally_preferences(synthetic_state())
        again = tally_preferences(state)
        self.assertEqual(again.globals()["tally"],
                         {"rice": 2, "wheat": 3})
        self.assertEqual(again.to_json(), state.to_json())


class TestPipelineCompilation(unittest.TestCase):
    def test_order_derived_from_dag_not_listing_order(self):
        # Listed backwards; the DAG still puts the tally first,
        # and the two tally-readers after it, alphabetically.
        ordered = compile_pipeline(
            [aggregate_outcome, compute_shares, tally_preferences])
        self.assertEqual([t.name for t in ordered],
                         ["tally_preferences", "aggregate_outcome",
                          "compute_shares"])

    def test_write_conflict_rejected_at_compile_time(self):
        clash = Transform("other_tally", reads=("nodes",),
                          writes=("globals.tally",),
                          fn=lambda s: s)
        with self.assertRaises(ValueError) as ctx:
            compile_pipeline([tally_preferences, clash])
        self.assertIn("write conflict", str(ctx.exception))

    def test_cycle_rejected_at_compile_time(self):
        a = Transform("a", reads=("globals.y",), writes=("globals.x",),
                      fn=lambda s: s)
        b = Transform("b", reads=("globals.x",), writes=("globals.y",),
                      fn=lambda s: s)
        with self.assertRaises(ValueError) as ctx:
            compile_pipeline([a, b])
        self.assertIn("cycle", str(ctx.exception))


class TestGovernance(unittest.TestCase):
    def test_every_result_is_unverified_and_needs_human(self):
        result = run_pipeline(synthetic_state(),
                              ms.plurality_pipeline())
        self.assertIs(result["verified"], False)
        self.assertIs(result["needs_human_decision"], True)
        # No transform can smuggle a verified flag in: the
        # final state carries no "verified" key at all.
        self.assertNotIn("verified", result["state"]["globals"])
        self.assertNotIn("verified", json.dumps(result["state"]))

    def test_result_json_round_trip_keeps_flags(self):
        result = run_pipeline(synthetic_state(),
                              ms.plurality_pipeline())
        restored = ms.result_from_json(ms.result_to_json(result))
        self.assertIs(restored["verified"], False)
        self.assertIs(restored["needs_human_decision"], True)
        self.assertEqual(restored["state"]["globals"]["outcome"], "wheat")
        self.assertEqual(restored["licence"], "MIT")

    def test_edges_survive_the_pipeline_unchanged(self):
        state = synthetic_state()
        result = run_pipeline(state, ms.plurality_pipeline())
        self.assertEqual(result["state"]["edges"], state.edges())
        self.assertEqual(result["state"]["nodes"], state.nodes())


class TestValidation(unittest.TestCase):
    def test_bad_preference_rejected(self):
        with self.assertRaises(ValueError):
            GraphState(nodes={"n1": {"preference": "", "weight": 1}})
        with self.assertRaises(ValueError):
            GraphState(nodes={"n1": {"weight": 1}})  # no preference

    def test_bad_weight_rejected(self):
        with self.assertRaises(ValueError):
            GraphState(nodes={"n1": {"preference": "wheat", "weight": 0}})
        with self.assertRaises(ValueError):
            GraphState(nodes={"n1": {"preference": "wheat",
                                     "weight": -2}})
        with self.assertRaises(ValueError):
            GraphState(nodes={"n1": {"preference": "wheat",
                                     "weight": "heavy"}})

    def test_state_json_round_trip(self):
        state = synthetic_state()
        restored = GraphState.from_json(state.to_json())
        self.assertEqual(restored, state)
        self.assertEqual(hash(restored), hash(state))
        self.assertEqual(restored.to_json(), state.to_json())


if __name__ == "__main__":
    unittest.main()
