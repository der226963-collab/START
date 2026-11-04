"""A tiny MLP in NumPy, written so every step is readable.

Architecture: input -> hidden (ReLU) -> output (softmax).
Training: full-batch gradient descent on cross-entropy loss.
No PyTorch, no hidden magic — this is the learning part.
"""
import numpy as np


class MLP:
    def __init__(self, input_size, hidden_size, output_size, seed=42):
        rng = np.random.default_rng(seed)
        # Xavier-style init keeps early gradients in a sane range.
        self.W1 = rng.normal(0, np.sqrt(2.0 / input_size), (input_size, hidden_size))
        self.b1 = np.zeros(hidden_size)
        self.W2 = rng.normal(0, np.sqrt(2.0 / hidden_size), (hidden_size, output_size))
        self.b2 = np.zeros(output_size)

    def _forward(self, X):
        h = X @ self.W1 + self.b1
        a = np.maximum(0, h)  # ReLU
        logits = a @ self.W2 + self.b2
        # Stable softmax
        logits = logits - logits.max(axis=1, keepdims=True)
        exp = np.exp(logits)
        probs = exp / exp.sum(axis=1, keepdims=True)
        return h, a, probs

    def predict(self, X):
        _, _, probs = self._forward(np.atleast_2d(X))
        return probs.argmax(axis=1)

    def predict_proba(self, X):
        _, _, probs = self._forward(np.atleast_2d(X))
        return probs

    def train(self, X, y, epochs=300, lr=0.1, verbose=False):
        """Return a list of losses, one per epoch."""
        n = len(X)
        losses = []
        for epoch in range(epochs):
            h, a, probs = self._forward(X)
            # Cross-entropy loss
            loss = -np.log(probs[np.arange(n), y] + 1e-12).mean()
            losses.append(float(loss))

            # Back-propagation
            grad_logits = probs.copy()
            grad_logits[np.arange(n), y] -= 1
            grad_logits /= n

            grad_W2 = a.T @ grad_logits
            grad_b2 = grad_logits.sum(axis=0)
            grad_a = grad_logits @ self.W2.T
            grad_h = grad_a * (h > 0)  # ReLU derivative
            grad_W1 = X.T @ grad_h
            grad_b1 = grad_h.sum(axis=0)

            self.W2 -= lr * grad_W2
            self.b2 -= lr * grad_b2
            self.W1 -= lr * grad_W1
            self.b1 -= lr * grad_b1

            if verbose and (epoch % 50 == 0 or epoch == epochs - 1):
                acc = (self.predict(X) == y).mean()
                print(f"epoch {epoch:4d}  loss {loss:.4f}  train acc {acc:.2%}")
        return losses
