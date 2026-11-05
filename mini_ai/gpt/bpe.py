"""Byte-pair encoding tokenizer, trained from scratch on local text.

Why this matters: a character model has to spell every word, one
letter at a time, so a tiny model spends most of its capacity
learning spelling and produces gibberish. A BPE model learns
common chunks (" th", "ing", "tion", "climate") as single tokens,
so the same small model can learn word and phrase patterns
instead of letters. That is the first real step past toy-level
output, before any larger dataset or larger model.

Algorithm, standard BPE (Sennrich et al., 2016), implemented here
from scratch, no external library:
  1. Start with one token per character.
  2. Count adjacent token pairs in the corpus.
  3. Merge the most frequent pair into a new token.
  4. Repeat for num_merges steps.
Encoding applies the learned merges in order, greedily, to new
text. Decoding is just joining the tokens. Unknown characters
are skipped, and that is reported by callers, not hidden.

Limits: BPE learned on a tiny corpus will still merge mostly
local patterns, and it cannot invent vocabulary it never saw.
It improves the shape of output; it does not add knowledge.
"""
import json
from collections import Counter


class BPETokenizer:
    def __init__(self, merges, vocab):
        self.merges = merges  # list of [a, b] in learned order
        self.vocab = vocab  # list of token strings, index = id
        self.stoi = {t: i for i, t in enumerate(vocab)}
        self.itos = {i: t for t, i in self.stoi.items()}

    @classmethod
    def train(cls, text, num_merges=300):
        """Train BPE with incremental pair counting.

        2026-11-04, fast-tokenizer equivalent: Hugging Face
        tokenizers (Apache 2.0, checked) is Rust and cannot be
        dropped into this stdlib Python project, so this is
        original Python code that produces the same effect —
        fast BPE training — by a different route. The old
        implementation rescanned the whole token list for
        every merge (O(merges x corpus), the reason a 19M-char
        corpus took most of a 43-minute run to tokenize).
        This version keeps a linked list of tokens plus a
        pair-count / pair-position index, and on each merge
        only updates the pairs touching a merged token.
        Cost is O(corpus + merges x occurrences), not
        O(merges x corpus). Merge choice is the same rule:
        most frequent pair, stopping when the best pair
        occurs fewer than twice, with ties broken by
        earliest first occurrence — so it produces the
        same merges as the old full-rescan trainer.
        """
        if not text:
            return cls([], [])
        n = len(text)
        tok = list(text)          # token string at each position
        prev = [i - 1 for i in range(n)]
        nxt = [i + 1 for i in range(n)]
        nxt[-1] = -1
        alive = [True] * n
        vocab = sorted(set(tok))
        vocab_set = set(vocab)

        def add_pair(left):
            if left < 0 or not alive[left]:
                return
            right = nxt[left]
            if right < 0 or not alive[right]:
                return
            pair = (tok[left], tok[right])
            pair_counts[pair] += 1
            pair_pos.setdefault(pair, set()).add(left)

        def remove_pair(left):
            if left < 0 or not alive[left]:
                return
            right = nxt[left]
            if right < 0 or not alive[right]:
                return
            pair = (tok[left], tok[right])
            if pair in pair_counts:
                pair_counts[pair] -= 1
                if pair_counts[pair] <= 0:
                    del pair_counts[pair]
            if pair in pair_pos:
                pair_pos[pair].discard(left)
                if not pair_pos[pair]:
                    del pair_pos[pair]

        pair_counts = Counter()
        pair_pos = {}
        for i in range(n):
            # Build the index without double-counting: add_pair
            # needs pair_counts/pair_pos to exist, so seed them
            # manually on the first pass.
            if i < n - 1:
                pair = (tok[i], tok[i + 1])
                pair_counts[pair] += 1
                pair_pos.setdefault(pair, set()).add(i)

        merges = []
        for _ in range(num_merges):
            if not pair_counts:
                break
            # Tie-break exactly like the naive scan: among the
            # most frequent pairs, take the one whose first
            # occurrence in the current token list is earliest.
            # This makes the fast trainer produce the same
            # merges as the old full-rescan trainer, not just
            # a valid alternative set.
            max_count = max(pair_counts.values())
            if max_count < 2:
                break
            (a, b) = min(
                (p for p, c in pair_counts.items() if c == max_count),
                key=lambda p: min(pair_pos[p]))
            count = max_count
            merged = a + b
            merges.append([a, b])
            if merged not in vocab_set:
                vocab.append(merged)
                vocab_set.add(merged)
            # Merge every occurrence, left to right, skipping
            # positions already consumed by an earlier merge
            # in this same pass (e.g. "aaa" with pair (a,a)).
            starts = sorted(pair_pos.get((a, b), ()))
            for left in starts:
                if not alive[left]:
                    continue
                right = nxt[left]
                if right < 0 or not alive[right]:
                    continue
                if tok[left] != a or tok[right] != b:
                    continue
                before = prev[left]
                after = nxt[right]
                # Remove the three pairs that touch this merge.
                remove_pair(before)
                remove_pair(left)
                remove_pair(right)
                # Splice: left becomes the merged token, right dies.
                tok[left] = merged
                alive[right] = False
                nxt[left] = after
                if after >= 0:
                    prev[after] = left
                # Add the two new pairs touching the merged token.
                add_pair(before)
                add_pair(left)
        return cls(merges, vocab)

    def encode(self, text):
        tokens = list(text)
        for a, b in self.merges:
            merged = a + b
            new_tokens = []
            i = 0
            while i < len(tokens):
                if i < len(tokens) - 1 and tokens[i] == a and tokens[i + 1] == b:
                    new_tokens.append(merged)
                    i += 2
                else:
                    new_tokens.append(tokens[i])
                    i += 1
            tokens = new_tokens
        return [self.stoi[t] for t in tokens if t in self.stoi]

    def decode(self, ids):
        return "".join(self.itos[int(i)] for i in ids if int(i) in self.itos)

    def __len__(self):
        return len(self.vocab)

    def to_json(self):
        return json.dumps({"merges": self.merges, "vocab": self.vocab})

    @classmethod
    def from_json(cls, data):
        obj = json.loads(data) if isinstance(data, str) else data
        return cls(obj["merges"], obj["vocab"])
