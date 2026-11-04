"""MiniGPT: a small decoder-only transformer, built to be read.

This is the step past the v1 classifier. v1 answered 'which intent
is this?' This model answers a harder question: 'what character
comes next?' Train it on text, and it learns patterns in that text
— first letters and spaces, then words, then short phrases.

The BPE tokenizer is stdlib-only and always available. The torch
models are optional: if torch is not installed, importing this
package still works, and the model names are None, matching the
skip behaviour in tests/test_gpt.py.
"""
from .bpe import BPETokenizer

try:
    from .model import MiniGPT, GPTConfig, CharTokenizer
except ImportError:  # torch not installed
    MiniGPT = GPTConfig = CharTokenizer = None

__all__ = ["MiniGPT", "GPTConfig", "CharTokenizer", "BPETokenizer"]
