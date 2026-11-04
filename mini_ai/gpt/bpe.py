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
        tokens = list(text)
        vocab = sorted(set(tokens))
        merges = []
        for _ in range(num_merges):
            pairs = Counter()
            for i in range(len(tokens) - 1):
                pairs[(tokens[i], tokens[i + 1])] += 1
            if not pairs:
                break
            (a, b), count = pairs.most_common(1)[0]
            if count < 2:
                break
            merged = a + b
            merges.append([a, b])
            if merged not in vocab:
                vocab.append(merged)
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
