"""Research-roles tests (SciAgents role-pattern rebuild).

Run from core-spine/ with:
    .venv/bin/python -m unittest discover -s tests -v
Synthetic data only (adapters.research_roles.synthetic_input):
no network, no LLM, no paid API, no SciAgents code. Never claim a
test passed unless it ran here.
"""

import json
import os
import unittest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from adapters import research_roles as rr  # noqa: E402

TEXT, QUESTION = rr.synthetic_input()


class TestOntologist(unittest.TestCase):
    def test_synthetic_terms_are_counted(self):
        ontology = rr.extract_ontology(TEXT)
        by_term = {t["term"]: t["occurrences"] for t in ontology["terms"]}
        # Hand-counted from the four synthetic sentences:
        # silk and fibres appear in all four; energy, load, matrix
        # and stiff in two each; the rest once.
        self.assertEqual(by_term["silk"], 4)
        self.assertEqual(by_term["fibres"], 4)
        self.assertEqual(by_term["energy"], 2)
        self.assertEqual(by_term["load"], 2)
        self.assertEqual(by_term["matrix"], 2)
        self.assertEqual(by_term["stiff"], 2)
        self.assertEqual(by_term["store"], 1)
        # Terms are sorted by occurrences descending, then term.
        self.assertEqual(ontology["terms"][0]["term"], "fibres")
        self.assertEqual(ontology["terms"][1]["term"], "silk")
        self.assertEqual(ontology["terms"][0]["occurrences"], 4)
        # A term's definition is only its first source sentence.
        self.assertEqual(
            ontology["terms"][1]["first_seen_in"],
            "Silk fibres store elastic energy.")
        self.assertEqual(ontology["source_sentences"], 4)

    def test_synthetic_relations_are_cooccurrence(self):
        ontology = rr.extract_ontology(TEXT)
        by_pair = {(r["subject"], r["object"]): r["occurrences"]
                   for r in ontology["relations"]}
        # fibres + silk co-occur in all four sentences; the pair is
        # order-independent, so it counts once per sentence.
        self.assertEqual(by_pair[("fibres", "silk")], 4)
        self.assertEqual(by_pair[("energy", "fibres")], 2)
        self.assertEqual(by_pair[("energy", "silk")], 2)
        self.assertEqual(by_pair[("fibres", "load")], 2)
        self.assertTrue(all(r["relation"] == "co-occurs-with"
                            for r in ontology["relations"]))
        self.assertEqual(ontology["relations"][0]["subject"], "fibres")
        self.assertEqual(ontology["relations"][0]["object"], "silk")

    def test_empty_text_yields_empty_ontology(self):
        ontology = rr.extract_ontology("   ")
        self.assertEqual(ontology["terms"], [])
        self.assertEqual(ontology["relations"], [])
        self.assertEqual(ontology["source_sentences"], 0)
        self.assertIs(ontology["verified"], False)
        self.assertTrue(ontology["needs_human_decision"])

    def test_non_string_text_is_rejected(self):
        with self.assertRaises(ValueError):
            rr.extract_ontology(None)


class TestScientist(unittest.TestCase):
    def test_proposal_has_exactly_the_seven_keys(self):
        ontology = rr.extract_ontology(TEXT)
        proposal = rr.draft_proposal(ontology, QUESTION)
        self.assertEqual(set(proposal), set(rr.PROPOSAL_KEYS))
        self.assertEqual(len(proposal), 7)
        self.assertEqual(list(rr.PROPOSAL_KEYS), [
            "hypothesis", "outcome", "mechanisms",
            "design_principles", "unexpected_properties",
            "comparison", "novelty"])
        self.assertEqual(rr.validate_proposal_schema(proposal), [])

    def test_proposal_fields_are_nonempty_and_grounded(self):
        ontology = rr.extract_ontology(TEXT)
        proposal = rr.draft_proposal(ontology, QUESTION)
        for key in rr.PROPOSAL_KEYS:
            value = proposal[key]
            if isinstance(value, str):
                self.assertTrue(value.strip(), key)
            else:
                self.assertTrue(value, key)
        # The hypothesis is templated from the three most frequent
        # terms: fibres, silk, energy.
        self.assertIn("fibres", proposal["hypothesis"])
        self.assertIn("silk", proposal["hypothesis"])
        self.assertIn("energy", proposal["hypothesis"])
        self.assertIn(QUESTION, proposal["hypothesis"])
        # Novelty is honestly unassessed; comparison has no baseline.
        self.assertIn("Unassessed", proposal["novelty"])
        self.assertIn("No baseline", proposal["comparison"])

    def test_mechanisms_come_from_top_relations(self):
        ontology = rr.extract_ontology(TEXT)
        proposal = rr.draft_proposal(ontology, QUESTION)
        self.assertEqual(len(proposal["mechanisms"]), 3)
        self.assertIn("fibres", proposal["mechanisms"][0])
        self.assertIn("silk", proposal["mechanisms"][0])
        self.assertIn("4 shared sentence(s)",
                      proposal["mechanisms"][0])

    def test_empty_ontology_or_question_is_rejected(self):
        with self.assertRaises(ValueError):
            rr.draft_proposal(rr.extract_ontology("   "), QUESTION)
        with self.assertRaises(ValueError):
            rr.draft_proposal(rr.extract_ontology(TEXT), "  ")

    def test_proposal_json_round_trip_keeps_exactly_seven_keys(self):
        ontology = rr.extract_ontology(TEXT)
        proposal = rr.draft_proposal(ontology, QUESTION)
        restored = rr.proposal_from_json(rr.proposal_to_json(proposal))
        self.assertEqual(restored, proposal)
        self.assertEqual(set(restored), set(rr.PROPOSAL_KEYS))


class TestCritic(unittest.TestCase):
    def test_drafted_proposal_passes_all_checks(self):
        ontology = rr.extract_ontology(TEXT)
        proposal = rr.draft_proposal(ontology, QUESTION)
        critique = rr.critique_proposal(proposal, ontology)
        self.assertEqual(critique["verdict"], "PASSED")
        self.assertEqual(critique["failures"], [])
        self.assertTrue(all(c["passed"] for c in critique["checks"]))
        self.assertEqual(len(critique["checks"]), 6)
        self.assertIs(critique["verified"], False)
        self.assertTrue(critique["needs_human_decision"])

    def test_empty_mechanisms_is_rejected(self):
        ontology = rr.extract_ontology(TEXT)
        proposal = rr.draft_proposal(ontology, QUESTION)
        proposal["mechanisms"] = []
        critique = rr.critique_proposal(proposal, ontology)
        self.assertEqual(critique["verdict"], "FAILED")
        self.assertIn("mechanisms_grounded", critique["failures"])
        self.assertIn("all_fields_nonempty", critique["failures"])

    def test_ungrounded_hypothesis_is_rejected(self):
        ontology = rr.extract_ontology(TEXT)
        proposal = rr.draft_proposal(ontology, QUESTION)
        proposal["hypothesis"] = (
            "Combining zirconium with titanium changes quantum foam.")
        critique = rr.critique_proposal(proposal, ontology)
        self.assertEqual(critique["verdict"], "FAILED")
        self.assertIn("hypothesis_grounded", critique["failures"])

    def test_missing_and_extra_keys_are_rejected(self):
        ontology = rr.extract_ontology(TEXT)
        proposal = rr.draft_proposal(ontology, QUESTION)
        del proposal["comparison"]
        proposal["extra_claim"] = "unverified extra field"
        problems = rr.validate_proposal_schema(proposal)
        self.assertTrue(any("missing keys" in p for p in problems))
        self.assertTrue(any("extra keys" in p for p in problems))
        critique = rr.critique_proposal(proposal, ontology)
        self.assertEqual(critique["verdict"], "FAILED")
        self.assertIn("schema_exact", critique["failures"])
        self.assertIn("comparison_present", critique["failures"])

    def test_asserted_novelty_is_rejected(self):
        ontology = rr.extract_ontology(TEXT)
        proposal = rr.draft_proposal(ontology, QUESTION)
        proposal["novelty"] = (
            "This idea is highly novel and has never been tried.")
        critique = rr.critique_proposal(proposal, ontology)
        self.assertEqual(critique["verdict"], "FAILED")
        self.assertIn("novelty_not_asserted", critique["failures"])


class TestPipeline(unittest.TestCase):
    def test_full_pipeline_on_synthetic_input(self):
        result = rr.run_pipeline(TEXT, QUESTION)
        self.assertEqual(result["verdict"], "PASSED")
        self.assertIs(result["verified"], False)
        self.assertTrue(result["needs_human_decision"])
        self.assertEqual(set(result["proposal"]),
                         set(rr.PROPOSAL_KEYS))
        self.assertEqual(result["critique"]["verdict"], "PASSED")
        self.assertEqual(result["question"], QUESTION)
        terms = {t["term"] for t in result["ontology"]["terms"]}
        self.assertIn("silk", terms)
        # The whole result is plain JSON-able (wire format is JSON).
        json.dumps(result)

    def test_pipeline_with_failing_override_is_failed(self):
        ontology = rr.extract_ontology(TEXT)
        bad = rr.draft_proposal(ontology, QUESTION)
        bad["mechanisms"] = []
        bad["novelty"] = "This is completely novel."
        result = rr.run_pipeline(TEXT, QUESTION, proposal_override=bad)
        self.assertEqual(result["verdict"], "FAILED")
        self.assertEqual(result["critique"]["verdict"], "FAILED")
        self.assertIs(result["verified"], False)
        self.assertTrue(result["needs_human_decision"])

    def test_pipeline_with_non_dict_override_is_failed(self):
        result = rr.run_pipeline(TEXT, QUESTION,
                                 proposal_override="not a proposal")
        self.assertEqual(result["verdict"], "FAILED")
        self.assertIs(result["verified"], False)

    def test_module_source_never_sets_verified_true(self):
        here = os.path.dirname(__file__)
        path = os.path.join(here, "..", "adapters", "research_roles.py")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn("verified=True", source)
        self.assertNotIn("verified = True", source)
        self.assertIn('"verified": False', source)
        # No LLM, no paid API, no new dependency: stdlib only, and
        # no SciAgents code imported (it is cited in the docstring
        # as design inspiration only).
        self.assertNotIn("import openai", source)
        self.assertNotIn("import requests", source)
        self.assertNotIn("import SciAgents", source)
        self.assertNotIn("from SciAgents", source)


if __name__ == "__main__":
    unittest.main()
