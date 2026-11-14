"""Versioned JSON-envelope persistence for START planning (ISSUE-27).

Public API (see :mod:`persistence.envelope` for the full contract):

* :data:`KINDS` — the only kinds a persisted file may carry.
* :func:`save_envelope` — atomically save a payload as an envelope.
* :func:`load_envelope` — load and validate an envelope, payload verbatim.

Paths are always caller-chosen; there is no default store directory.
JSON only, standard library only.
"""
from __future__ import annotations

from persistence.envelope import ENVELOPE_KEYS, KINDS, load_envelope, save_envelope

__all__ = ["KINDS", "ENVELOPE_KEYS", "save_envelope", "load_envelope"]
