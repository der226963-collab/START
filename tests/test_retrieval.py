"""Tests for mini_ai/retrieval.py: token overlap retrieval + intent gate.

These are behaviour tests, not model tests: they run in under a
second with no weights. The probe file is used only as a test set
here, never as a knowledge base.
"""
import json
from pathlib import Path

from mini_ai.retrieval import load_kb, match_intent, tokenize

ROOT = Path(__file__).resolve().parent.parent


def test_tokenize_stems_and_drops_stopwords():
    toks = tokenize("How many people have no decent place to live?")
    # stopwords (how, have, no, to) dropped; plurals stemmed
    assert "mani" in toks or "many" in toks
    assert "peopl" in toks or "people" in toks
    assert "how" not in toks
    assert "live" in toks


def test_kb_has_34_facts():
    kb = load_kb(str(ROOT / "data" / "instructions.txt"))
    assert len(kb) == 34


def test_retrieve_finds_care_hours_fact():
    kb = load_kb(str(ROOT / "data" / "instructions.txt"))
    ranked = kb.retrieve("How many hours a day go to unpaid care?", top_k=1)
    assert ranked
    score, _, _, fact = ranked[0]
    assert score >= 0.2
    assert "16.4 billion hours" in fact["response"]


def test_retrieve_needs_question_overlap():
    kb = load_kb(str(ROOT / "data" / "instructions.txt"))
    # "who decides" shares only a response token ("decide") with a
    # fact; it must not retrieve, because it matches no question.
    ranked = kb.retrieve("who decides", top_k=1)
    assert ranked[0][0] == 0.0


def test_match_intent_gates_known_intents():
    intent, score, _ = match_intent("who decides")
    assert intent == "explain_ai"
    assert score == 1.0
    intent, score, _ = match_intent("plan this with me")
    assert intent == "planning"
    assert score == 1.0


def test_match_intent_does_not_gate_fact_questions():
    intent, _, _ = match_intent("How many hours a day go to unpaid care?")
    assert intent is None
    intent, _, _ = match_intent("Do buildings take a large share of energy?")
    assert intent is None


def test_probe_retrieval_accuracy():
    """Retrieval must find the right fact for 5 of 6 probe facts.

    The care-kinds probe is the known miss: it is ambiguous with the
    care-hours fact (both share 'care' vocabulary).
    """
    kb = load_kb(str(ROOT / "data" / "instructions.txt"))
    probe = [json.loads(l) for l in
             (ROOT / "eval" / "finetune-probe-v5.jsonl").read_text().splitlines()
             if l.strip()]
    fact_rows = [r for r in probe if r["source"].startswith("probe:")
                 and r["source"] not in ("probe:thanks", "probe:help")]
    assert len(fact_rows) == 6
    right = 0
    for row in fact_rows:
        ranked = kb.retrieve(row["instruction"], top_k=1)
        if ranked and ranked[0][3]["response"] == row["response"].strip():
            right += 1
    assert right == 5
