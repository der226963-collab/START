"""Research roles (Module 9) — original Python, stdlib only.

Design inspiration: SciAgents Discovery (lamm-mit/SciAgentsDiscovery,
Apache-2.0 — verified in the sweep from the repo's own LICENSE file;
1,036 lines of Python, last commit 2025-05-09). The sweep's verdict
for it was DEFER: the prototype needs a paid OpenAI API key, the
Semantic Scholar API, and a separate lamm-mit/GraphReasoning
package, and it is a narrow bio-inspired-materials demo, not a
library. Its Ontologist -> Scientist -> Critic role pattern and its
7-key structured JSON proposal schema survive as a design note for
original Python code. **No SciAgents code was copied** — this module
was written from the role pattern and the schema shape only — and
nothing was adopted as a dependency: no LLM, no paid API, no new
dependency, ``requirements.txt`` unchanged. No network.

The 7 keys are the seven aspects the SciAgents paper lists for a
Scientist_1 proposal (Ghafarollahi & Buehler, Adv. Mater. 2025,
"SciAgents: Automating Scientific Discovery Through Bioinspired
Multi-Agent Intelligent Graph Reasoning", PMC12138853): hypothesis,
outcome, mechanisms, design principles, unexpected properties,
comparison, and novelty. Here they are snake_case JSON keys:

    PROPOSAL_KEYS = ("hypothesis", "outcome", "mechanisms",
                     "design_principles", "unexpected_properties",
                     "comparison", "novelty")

Semantics (original, defined here, not copied):
- The roles are DETERMINISTIC, rule-based stages over supplied
  text — there is no language model anywhere in this module.
  ``extract_ontology(text)`` (Ontologist) tokenises the supplied
  text, counts content words (length >= 4, stopwords removed),
  and records co-occurrence relations between terms that appear
  in the same sentence. A term's "definition" is only the first
  source sentence it appears in — this module never invents a
  definition, and it never claims a term means anything beyond
  what the supplied text says.
- ``draft_proposal(ontology, question)`` (Scientist) builds a
  proposal in exactly the 7-key schema, templated from the
  ontology's most frequent terms and relations. The proposal
  itself is exactly those 7 keys — no more, no fewer — and the
  governance flags live in the pipeline envelope, not in the
  proposal. Two fields are honest about what this module cannot
  do: ``unexpected_properties`` reports that none was identified
  in the supplied text, and ``novelty`` states novelty is
  unassessed because no literature check is performed here.
  ``comparison`` likewise states that no baseline was supplied.
- ``critique_proposal(proposal, ontology)`` (Critic) checks the
  proposal against explicit, deterministic criteria and returns
  a verdict: "PASSED" only if every check passes, "FAILED"
  otherwise. A proposal that fails any check is marked FAILED,
  never passed. The checks are: (1) the schema is exactly the
  7 keys; (2) every field is non-empty; (3) the hypothesis
  mentions at least one ontology term (grounding — a hypothesis
  about terms that are not in the ontology fails); (4) every
  mechanism mentions at least one ontology term, and the list
  is non-empty; (5) the novelty field must NOT assert novelty
  without qualification — it must state novelty is unassessed
  or not verified (a proposal claiming novelty it cannot show
  fails); (6) the comparison field is present and non-empty.
  "PASSED" means only "passed these explicit rule checks" —
  it is not verification of the science.
- GOVERNANCE: no stage may set verified to True. Every result
  this module produces carries verified False and
  needs_human_decision True. A proposal is a model result,
  never a verified plan: the real verify step plus human
  approval still decide verification. The wire format stays
  JSON: ontologies, proposals, critiques and pipeline results
  are plain JSON-able dicts (schema_version "1.0.0").
- The Scientist_2 expansion step from the original prototype
  (a second scientist agent expanding the draft with specific
  experimental and simulation approaches) is NOT a separate
  stage here: without a language model there is nothing to
  expand with beyond the same deterministic templates, so the
  Scientist stage drafts the full 7-key proposal directly.
  That is recorded as a limitation below.

All data here is synthetic; no real literature, no external API.
"""

import json
import re

SCHEMA_VERSION = "1.0.0"
LICENCE = "Apache-2.0"
PROVENANCE = ("START original — SciAgents role pattern as design "
              "inspiration only, no code copied")

# The seven aspects of a Scientist_1 proposal, per the SciAgents
# paper (hypothesis, outcome, mechanisms, design principles,
# unexpected properties, comparison, novelty), as snake_case keys.
PROPOSAL_KEYS = ("hypothesis", "outcome", "mechanisms",
                 "design_principles", "unexpected_properties",
                 "comparison", "novelty")

STOPWORDS = frozenset("""
a an and are as at be by can do for from has have he her his how i if
in into is it its may more most no not of on one or our out per say
see she so some such than that the their them then there these they
this to use used using was we what when where which who will with
you your also been being but did does had him its nor off own same
should too very was were what when where which while who whom why
yet about above after again against all any because before below
between both down during each few further here once only other over
same under until up upon via within without would could shall
""".split())

_WORD_RE = re.compile(r"[a-z][a-z\-]{2,}")
_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]?")


def _sentences(text):
    """Split text into sentences, stripped, non-empty, in order."""
    return [s.strip() for s in _SENTENCE_RE.findall(text)
            if s.strip()]


def _content_words(sentence):
    """Lowercased content words of a sentence, in order, deduped."""
    words = _WORD_RE.findall(sentence.lower())
    seen = []
    for word in words:
        if len(word) < 4 or word in STOPWORDS:
            continue
        if word not in seen:
            seen.append(word)
    return seen


def extract_ontology(text):
    """Ontologist stage: extract terms and relations from text.

    Returns a plain JSON-able dict with "terms" (each a dict with
    "term", "occurrences" and the first source sentence it appears
    in, sorted by occurrences descending then term) and "relations"
    (each a dict with "subject", "relation" ("co-occurs-with"),
    "object" and "occurrences", sorted the same way). Terms and
    relations come only from the supplied text. Empty or
    whitespace-only text yields empty terms and relations — never
    an error, never invented content. verified is always False.
    """
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    sentences = _sentences(text)
    counts = {}
    first_sentence = {}
    relation_counts = {}
    for sentence in sentences:
        words = _content_words(sentence)
        for word in words:
            counts[word] = counts.get(word, 0) + 1
            if word not in first_sentence:
                first_sentence[word] = sentence
        for i, first in enumerate(words):
            for second in words[i + 1:]:
                # Order-independent pair: the same two terms
                # co-occurring in different sentence orders count
                # as one relation, not two.
                pair = tuple(sorted((first, second)))
                relation_counts[pair] = relation_counts.get(pair, 0) + 1
    terms = [{
        "term": term,
        "occurrences": counts[term],
        "first_seen_in": first_sentence[term],
    } for term in sorted(counts, key=lambda t: (-counts[t], t))]
    relations = [{
        "subject": pair[0],
        "relation": "co-occurs-with",
        "object": pair[1],
        "occurrences": relation_counts[pair],
    } for pair in sorted(relation_counts,
                         key=lambda p: (-relation_counts[p], p))]
    return {
        "schema_version": SCHEMA_VERSION,
        "licence": LICENCE,
        "provenance": PROVENANCE,
        "terms": terms,
        "relations": relations,
        "source_sentences": len(sentences),
        "verified": False,
        "needs_human_decision": True,
    }


def draft_proposal(ontology, question):
    """Scientist stage: draft a proposal in exactly the 7-key schema.

    ``ontology`` is an ``extract_ontology`` result (or any dict
    with "terms" and "relations" in that shape) and ``question``
    is the research question the proposal addresses. The proposal
    dict has exactly the 7 keys in PROPOSAL_KEYS — no more, no
    fewer — and every value is non-empty. The hypothesis is
    templated from the ontology's most frequent terms; mechanisms
    come from its top relations; design principles from its top
    terms. Raises ValueError if the ontology has no terms (a
    proposal cannot be drafted from an empty ontology).
    """
    if not isinstance(ontology, dict):
        raise ValueError("ontology must be a dict")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string")
    terms = ontology.get("terms") or []
    relations = ontology.get("relations") or []
    if not terms:
        raise ValueError(
            "cannot draft a proposal from an empty ontology: "
            "no terms were extracted from the supplied text")
    top = [t["term"] for t in terms[:3]]
    first = top[0]
    second = top[1] if len(top) > 1 else top[0]
    third = top[2] if len(top) > 2 else top[0]
    mechanisms = []
    for rel in relations[:3]:
        mechanisms.append(
            f"{rel['subject']} co-occurs with {rel['object']} in the "
            f"supplied text ({rel['occurrences']} shared sentence(s)), "
            f"suggesting a {rel['subject']}-{rel['object']} interaction "
            f"to investigate.")
    if not mechanisms:
        mechanisms.append(
            f"No co-occurrence relation was found in the supplied "
            f"text; the {first}-{second} interaction is proposed "
            f"from the two most frequent terms only.")
    proposal = {
        "hypothesis": (
            f"Combining {first} with {second} changes {third} in a "
            f"way that addresses the question: {question.strip()}"),
        "outcome": (
            f"If the hypothesis holds, a {first}-{second} combination "
            f"would show a measurable change in {third} relative to "
            f"{first} alone; if it does not hold, no such change "
            f"would be observed."),
        "mechanisms": mechanisms,
        "design_principles": [
            f"Design around the {first}-{second} interaction "
            f"observed in the supplied text.",
            f"Vary {third} while holding {first} fixed, so the "
            f"effect of {second} can be isolated.",
        ],
        "unexpected_properties": (
            "None identified in the supplied text: no property "
            "outside the extracted terms was observed. Any "
            "unexpected property would need experimental "
            "observation, not text extraction."),
        "comparison": (
            "No baseline was supplied with the input, so no "
            "comparison against prior work was performed; "
            "comparison requires a supplied baseline or a "
            "literature check, neither of which this module "
            "performs."),
        "novelty": (
            "Unassessed: novelty requires a literature check, "
            "which this module does not perform; no novelty claim "
            "is made here."),
    }
    json.dumps(proposal)  # must be plain JSON-able, or raise here
    return proposal


def validate_proposal_schema(proposal):
    """Return a list of schema problems; empty list means valid.

    Problems are: not a dict; keys other than exactly the 7 in
    PROPOSAL_KEYS; any empty value (blank string, empty list).
    """
    problems = []
    if not isinstance(proposal, dict):
        return ["proposal is not a dict"]
    keys = set(proposal)
    expected = set(PROPOSAL_KEYS)
    if keys != expected:
        missing = sorted(expected - keys)
        extra = sorted(keys - expected)
        if missing:
            problems.append(f"missing keys: {missing}")
        if extra:
            problems.append(f"extra keys: {extra}")
    for key in PROPOSAL_KEYS:
        if key not in proposal:
            continue
        value = proposal[key]
        if isinstance(value, str) and not value.strip():
            problems.append(f"field {key!r} is an empty string")
        elif isinstance(value, list) and not value:
            problems.append(f"field {key!r} is an empty list")
        elif value is None:
            problems.append(f"field {key!r} is null")
    return problems


def _mentions_term(text, terms):
    """True if ``text`` mentions at least one ontology term."""
    lowered = text.lower()
    return any(term in lowered for term in terms)


def critique_proposal(proposal, ontology):
    """Critic stage: check a proposal against explicit criteria.

    Returns a plain JSON-able dict with "verdict" ("PASSED" only
    if every check passes, "FAILED" otherwise), "checks" (one
    entry per criterion, each with "name", "passed" and "detail")
    and "failures" (the names of the failed checks). A proposal
    that fails any check is marked FAILED, never passed.
    "PASSED" means only "passed these explicit rule checks" —
    it is not verification of the science. verified is always
    False and needs_human_decision always True.
    """
    if not isinstance(ontology, dict):
        raise ValueError("ontology must be a dict")
    terms = [t["term"] for t in (ontology.get("terms") or [])]
    checks = []

    schema_problems = validate_proposal_schema(proposal)
    checks.append({
        "name": "schema_exact",
        "passed": not schema_problems,
        "detail": ("proposal has exactly the 7 keys"
                   if not schema_problems
                   else "; ".join(schema_problems)),
    })

    if isinstance(proposal, dict):
        empty = [k for k in PROPOSAL_KEYS
                 if k in proposal and (
                     (isinstance(proposal[k], str)
                      and not proposal[k].strip())
                     or (isinstance(proposal[k], list)
                         and not proposal[k])
                     or proposal[k] is None)]
        checks.append({
            "name": "all_fields_nonempty",
            "passed": not empty,
            "detail": ("every field is non-empty"
                       if not empty
                       else f"empty fields: {empty}"),
        })
        hypothesis = proposal.get("hypothesis", "")
        checks.append({
            "name": "hypothesis_grounded",
            "passed": (isinstance(hypothesis, str) and bool(terms)
                       and _mentions_term(hypothesis, terms)),
            "detail": ("hypothesis mentions an ontology term"
                       if isinstance(hypothesis, str)
                       and _mentions_term(hypothesis, terms)
                       else "hypothesis mentions no ontology term"),
        })
        mechanisms = proposal.get("mechanisms")
        if isinstance(mechanisms, list) and mechanisms:
            ungrounded = [m for m in mechanisms
                          if not isinstance(m, str)
                          or not _mentions_term(m, terms)]
            checks.append({
                "name": "mechanisms_grounded",
                "passed": not ungrounded,
                "detail": ("every mechanism mentions an ontology term"
                           if not ungrounded
                           else f"{len(ungrounded)} mechanism(s) "
                           "mention no ontology term"),
            })
        else:
            checks.append({
                "name": "mechanisms_grounded",
                "passed": False,
                "detail": "mechanisms is not a non-empty list",
            })
        novelty = proposal.get("novelty", "")
        qualified = (isinstance(novelty, str)
                     and ("unassessed" in novelty.lower()
                          or "not verified" in novelty.lower()))
        checks.append({
            "name": "novelty_not_asserted",
            "passed": qualified,
            "detail": ("novelty is stated as unassessed / not "
                       "verified, so no novelty claim is made"
                       if qualified
                       else "novelty asserts novelty without "
                       "stating it is unassessed or not verified"),
        })
        comparison = proposal.get("comparison", "")
        checks.append({
            "name": "comparison_present",
            "passed": isinstance(comparison, str)
            and bool(comparison.strip()),
            "detail": ("comparison field is present and non-empty"
                       if isinstance(comparison, str)
                       and comparison.strip()
                       else "comparison field is missing or empty"),
        })
    else:
        for name in ("all_fields_nonempty", "hypothesis_grounded",
                     "mechanisms_grounded", "novelty_not_asserted",
                     "comparison_present"):
            checks.append({
                "name": name,
                "passed": False,
                "detail": "proposal is not a dict",
            })

    failures = [c["name"] for c in checks if not c["passed"]]
    return {
        "schema_version": SCHEMA_VERSION,
        "licence": LICENCE,
        "provenance": PROVENANCE,
        "verdict": "PASSED" if not failures else "FAILED",
        "checks": checks,
        "failures": failures,
        "verified": False,
        "needs_human_decision": True,
    }


def run_pipeline(text, question, proposal_override=None):
    """Run Ontologist -> Scientist -> Critic over supplied text.

    Returns a plain JSON-able envelope with the ontology, the
    proposal (drafted by the Scientist, or ``proposal_override``
    when one is supplied — the override path exists so a
    hand-made proposal can be put through the Critic), the
    critique, and the pipeline verdict (the Critic's verdict).
    verified is always False; needs_human_decision always True.
    A proposal that fails the Critic is marked FAILED here too.
    """
    ontology = extract_ontology(text)
    if proposal_override is None:
        proposal = draft_proposal(ontology, question)
    else:
        proposal = proposal_override
    critique = critique_proposal(proposal, ontology)
    result = {
        "schema_version": SCHEMA_VERSION,
        "licence": LICENCE,
        "provenance": PROVENANCE,
        "question": question,
        "ontology": ontology,
        "proposal": proposal,
        "critique": critique,
        "verdict": critique["verdict"],
        "verified": False,
        "needs_human_decision": True,
    }
    json.dumps(result)  # must be plain JSON-able, or raise here
    return result


def proposal_to_json(proposal):
    """Serialise a proposal to a JSON string (sorted keys)."""
    return json.dumps(proposal, sort_keys=True)


def proposal_from_json(text):
    """Deserialise a proposal. Schema is checked by the Critic."""
    return json.loads(text)


# Synthetic example input (clearly synthetic, not real literature):
# silk + energy, echoing the SciAgents paper's own validation
# example (a knowledge graph built from the words "silk" and
# "energy extensive"), written here as original sentences.
SYNTHETIC_TEXT = (
    "Silk fibres store elastic energy. "
    "Energy extensive composites combine silk fibres with a stiff matrix. "
    "The stiff matrix transfers load to the silk fibres. "
    "Silk fibres recover their shape after the load is removed."
)
SYNTHETIC_QUESTION = (
    "Can silk fibres improve the energy storage of a composite?"
)


def synthetic_input():
    """Return (text, question) for the synthetic silk/energy case."""
    return SYNTHETIC_TEXT, SYNTHETIC_QUESTION
