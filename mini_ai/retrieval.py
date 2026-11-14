"""Retrieval: look facts up at answer time instead of memorising them.

The knowledge base is data/instructions.txt (102 question/response
blocks after the v6 paraphrase expansion). Each distinct response is
one fact; the several question wordings for that fact (original +
paraphrases) are all kept as match surface, so a new phrasing can
still find the fact it asks about.

Matching is plain token overlap, no embeddings and no new
dependencies: lowercase, keep alphanumerics (so "16.4" stays one
token), drop stopwords, light stemming, then score a fact by how
many of the query's content tokens appear in its best question
wording (double weight) and in its response. This is deliberately
simple and explainable: if it ranks the wrong fact, the printed
scores show why.

The probe file (eval/finetune-probe-v5.jsonl) is NEVER loaded as a
knowledge base. It is only a test set. Retrieval must earn its
score on phrasings it has never seen.
"""
import re
from pathlib import Path

from mini_ai.data import INTENTS

# A question is treated as a known intent (answer from the intent
# system / adapter, no retrieval) when it overlaps a stored intent
# utterance by at least this fraction of its content tokens. The
# val intent questions all score 1.00 and the fact questions at
# most 0.33, so 0.5 sits in a wide gap.
INTENT_THRESHOLD = 0.5

STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "what", "which", "who", "whom", "whose", "when", "where", "why", "how",
    "do", "does", "did", "can", "could", "should", "would", "will", "shall",
    "may", "might", "must", "of", "in", "on", "at", "to", "for", "from",
    "with", "by", "and", "or", "but", "not", "no", "it", "its", "this",
    "that", "these", "those", "there", "here", "as", "than", "then", "so",
    "such", "if", "i", "you", "he", "she", "we", "they", "me", "him", "her",
    "us", "them", "my", "your", "his", "our", "their", "am", "have", "has",
    "had", "about", "into", "over", "under", "between", "per", "each",
    "isn", "aren", "wasn", "weren", "don", "doesn", "didn", "can", "couldn",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[.%][0-9]+)?")


def _stem(tok):
    """Light stemming so morphological variants match.

    Plural is stripped first, then the comparative, so "numbers" and
    "number" stem the same way ("numb"). "shares" -> "share",
    "buildings" -> "building", "warmest"/"warmer" -> "warm".
    """
    if len(tok) <= 3:
        return tok
    if tok.endswith("ies") and len(tok) - 3 >= 2:
        return tok[:-3] + "y"
    if tok.endswith("es"):
        if tok.endswith("ches") or tok.endswith("shes") or tok[-3] in "sxz":
            tok = tok[:-2]  # watches -> watch, boxes -> box
        else:
            tok = tok[:-1]  # shares -> share
    elif tok.endswith("s") and not tok.endswith("ss"):
        tok = tok[:-1]  # buildings -> building, hours -> hour
    if tok.endswith("est") and len(tok) - 3 >= 3:
        tok = tok[:-3]  # warmest -> warm
    elif tok.endswith("er") and len(tok) - 2 >= 3:
        tok = tok[:-2]  # warmer -> warm
    return tok


def tokenize(text):
    """Content tokens: lowercase, alphanumerics, stopwords dropped, stemmed."""
    out = []
    for tok in _TOKEN_RE.findall(text.lower()):
        if tok in STOPWORDS:
            continue
        out.append(_stem(tok))
    return out


def parse_instructions(path):
    """Parse data/instructions.txt into (question, response) blocks."""
    text = Path(path).read_text()
    pairs = []
    for block in text.split("### Instruction:"):
        block = block.strip()
        if not block or "### Response:" not in block:
            continue
        q, r = block.split("### Response:", 1)
        pairs.append((q.strip(), r.strip()))
    return pairs


class KnowledgeBase:
    """Facts grouped by response; each fact keeps all its question wordings."""

    def __init__(self, pairs):
        by_response = {}
        for q, r in pairs:
            if r not in by_response:
                by_response[r] = {
                    "response": r,
                    "questions": [],
                    "qtokens": [],
                    "rtokens": set(tokenize(r)),
                }
            by_response[r]["questions"].append(q)
            by_response[r]["qtokens"].append(set(tokenize(q)))
        self.facts = list(by_response.values())

    def __len__(self):
        return len(self.facts)

    def retrieve(self, query, top_k=1):
        """Best facts first: [(score, q_recall, r_recall, fact), ...].

        score = (2 * question-recall + response-recall) / 3, where each
        recall is the fraction of the query's content tokens found in
        the fact's best question wording / response.
        """
        qtok = set(tokenize(query))
        if not qtok:
            return []
        scored = []
        for fact in self.facts:
            best_q = 0.0
            for wt in fact["qtokens"]:
                overlap = len(qtok & wt)
                best_q = max(best_q, overlap / len(qtok))
            r_overlap = len(qtok & fact["rtokens"]) / len(qtok)
            score = (2 * best_q + r_overlap) / 3.0
            if best_q == 0:
                # A fact must match the question wording, not just its
                # response. Otherwise a one-word query like "who
                # decides" matches any response containing "decide"
                # and retrieves a fact about something else.
                score = 0.0
            scored.append((score, best_q, r_overlap, fact))
        scored.sort(key=lambda t: t[0], reverse=True)
        return scored[:top_k]


def match_intent(query, threshold=INTENT_THRESHOLD):
    """Best-matching known intent, or (None, score, utterance).

    Overlap is the fraction of the query's content tokens found in
    the stored utterance. Returns the intent only when the overlap
    clears the threshold; otherwise (None, best score, utterance).
    """
    qtok = set(tokenize(query))
    if not qtok:
        return None, 0.0, None
    best_intent, best_utt, best_ov = None, None, 0.0
    for intent, utterances in INTENTS.items():
        for utt in utterances:
            ov = len(qtok & set(tokenize(utt))) / len(qtok)
            if ov > best_ov:
                best_intent, best_utt, best_ov = intent, utt, ov
    if best_ov >= threshold:
        return best_intent, best_ov, best_utt
    return None, best_ov, best_utt


def load_kb(path="data/instructions.txt"):
    """Load the knowledge base from an instructions file."""
    return KnowledgeBase(parse_instructions(path))
