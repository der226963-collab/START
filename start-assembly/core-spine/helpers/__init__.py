"""Borrowed helpers (local assembly, 2026-11-11).

Small stdlib-only utilities copied from permissively licensed candidates
audited in batch 2 — see `borrowed_helpers.py` and `PROVENANCE.md`.
These are untrusted-input utilities (text chunking, URL canonicalisation)
and are NOT wired into any verify, governance, or decision path.
"""

from .borrowed_helpers import (
    chunk_by_word,
    chunk_content_hash,
    content_chunk_id,
    is_real_paragraph_end,
    normalize_url,
)

__all__ = [
    "chunk_by_word",
    "chunk_content_hash",
    "content_chunk_id",
    "is_real_paragraph_end",
    "normalize_url",
]
