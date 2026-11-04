"""Turn text into a bag-of-words vector, classify it, answer."""
import re

import numpy as np

from .data import INTENTS, RESPONSES
from .neural_net import MLP


def tokenize(text):
    return re.findall(r"[a-z]+", text.lower())


class Assistant:
    def __init__(self):
        self.labels = sorted(INTENTS)
        self.label_to_id = {label: i for i, label in enumerate(self.labels)}
        vocab = set()
        for examples in INTENTS.values():
            for ex in examples:
                vocab.update(tokenize(ex))
        self.vocab = sorted(vocab)
        self.word_to_id = {w: i for i, w in enumerate(self.vocab)}
        self.model = MLP(len(self.vocab), hidden_size=16, output_size=len(self.labels))

    def vectorize(self, text):
        vec = np.zeros(len(self.vocab))
        for word in tokenize(text):
            if word in self.word_to_id:
                vec[self.word_to_id[word]] = 1.0
        return vec

    def train(self, epochs=300, verbose=False):
        X, y = [], []
        for label, examples in INTENTS.items():
            for ex in examples:
                X.append(self.vectorize(ex))
                y.append(self.label_to_id[label])
        return self.model.train(np.array(X), np.array(y), epochs=epochs, verbose=verbose)

    def reply(self, text):
        vec = self.vectorize(text)
        if vec.sum() == 0:
            return "I don't recognise any words in that yet — try 'hello', 'help', or 'plan something', or add it as a new training example."
        probs = self.model.predict_proba(vec)[0]
        best = int(probs.argmax())
        if probs[best] < 0.4:
            return "I'm not sure what you mean yet. Try rephrasing, or teach me that sentence as a new example."
        return RESPONSES[self.labels[best]]
