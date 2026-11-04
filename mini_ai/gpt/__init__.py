"""MiniGPT: a small decoder-only transformer, built to be read.

This is the step past the v1 classifier. v1 answered 'which intent
is this?' This model answers a harder question: 'what character
comes next?' Train it on text, and it learns patterns in that text
— first letters and spaces, then words, then short phrases.
"""
from .model import MiniGPT, GPTConfig, CharTokenizer

__all__ = ["MiniGPT", "GPTConfig", "CharTokenizer"]
