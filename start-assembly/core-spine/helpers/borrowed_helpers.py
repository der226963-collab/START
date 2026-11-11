"""Borrowed helpers — text chunking and URL canonicalisation.

Copied, with the Apache-2.0 licence notices kept, from two permissively
licensed candidates audited in batch 2 of the borrowing audit
(`../source-audit/CEDAR_EGG_COGNEE_GRAPHITI_CRAWL4AI_AUDIT.md`):

* Cognee (topoteretes/cognee, Apache-2.0): `chunk_by_word` and
  `is_real_paragraph_end` from `cognee/tasks/chunks/chunk_by_word.py`
  (87 lines), and `chunk_content_hash` / `content_chunk_id` from
  `cognee/modules/chunking/chunk_id.py` (22 lines).
* Crawl4AI (unclecode/crawl4ai, Apache-2.0): `normalize_url` from
  `crawl4ai/utils.py` lines 2259-2358 (~100 lines) — extracted alone;
  the rest of that 3,786-line file was NOT copied.

These are the ONLY borrowed code in this assembly. They are stdlib-only
(`re`, `collections.abc`, `hashlib`, `uuid`, `urllib.parse`) — no
dependency was added. They are untrusted-input utilities (text chunking,
URL canonicalisation) and are NOT wired into any verify, governance, or
decision path: they cannot mark a plan verified, authorise anything, or
change a verdict. Full provenance in `PROVENANCE.md` in this folder.
"""

import re
from collections.abc import Iterator
from hashlib import sha256
from urllib.parse import urlencode, urljoin, urlparse, urlunparse, parse_qsl
from uuid import NAMESPACE_OID, UUID, uuid5

__all__ = [
    "chunk_by_word",
    "is_real_paragraph_end",
    "chunk_content_hash",
    "content_chunk_id",
    "normalize_url",
]


# ---------------------------------------------------------------------------
# Cognee — chunk_by_word / chunk_id
# Copyright Cognee contributors (topoteretes/cognee).
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# Copied verbatim from the Cognee sources named in the module docstring;
# no changes except extraction into this module (imports hoisted to the
# top of this file).
# ---------------------------------------------------------------------------


SENTENCE_ENDINGS = r"[.;!?…。！？]"
PARAGRAPH_ENDINGS = r"[\n\r]"


def is_real_paragraph_end(last_char: str, current_pos: int, text: str) -> bool:
    """
    Determine if the current position represents a valid paragraph end.

    The function checks if the last character indicates a possible sentence ending, then
    verifies if the subsequent characters lead to a valid paragraph end based on specific
    conditions.

    Parameters:
    -----------

        - last_char (str): The last processed character
        - current_pos (int): Current position in the text
        - text (str): The input text

    Returns:
    --------

        - bool: True if this is a real paragraph end, False otherwise
    """
    if re.match(SENTENCE_ENDINGS, last_char):
        return True
    j = current_pos + 1
    if j >= len(text):
        return False

    next_character = text[j]
    while j < len(text) and (re.match(PARAGRAPH_ENDINGS, next_character) or next_character == " "):
        j += 1
        if j >= len(text):
            return False
        next_character = text[j]

    return bool(next_character.isupper())


def chunk_by_word(data: str) -> Iterator[tuple[str, str]]:
    """
    Chunk text into words and sentence endings, preserving whitespace.

    Whitespace is included with the preceding word. Outputs can be joined with "" to
    recreate the original input.

    Parameters:
    -----------

        - data (str): The input string of text to be chunked into words and sentence
          endings.
    """
    current_chunk = ""
    i = 0

    while i < len(data):
        character = data[i]

        current_chunk += character

        if character == " ":
            yield (current_chunk, "word")
            current_chunk = ""
            i += 1
            continue

        if re.match(SENTENCE_ENDINGS, character):
            # Look ahead for whitespace
            next_i = i + 1
            while next_i < len(data) and data[next_i] == " ":
                current_chunk += data[next_i]
                next_i += 1

            is_paragraph_end = next_i < len(data) and re.match(PARAGRAPH_ENDINGS, data[next_i])
            yield (current_chunk, "paragraph_end" if is_paragraph_end else "sentence_end")
            current_chunk = ""
            i = next_i
            continue

        i += 1

    if current_chunk:
        yield (current_chunk, "word")


from hashlib import sha256
from uuid import NAMESPACE_OID, UUID, uuid5


def chunk_content_hash(text: str) -> str:
    """Stable hex digest of the chunk's exact text."""
    return sha256(text.encode("utf-8")).hexdigest()


def content_chunk_id(document_id, content_hash: str, occurrence: int) -> UUID:
    """Deterministic chunk id from (document, content, nth occurrence)."""
    return uuid5(NAMESPACE_OID, f"{document_id}:{content_hash}:{occurrence}")

# ---------------------------------------------------------------------------
# Crawl4AI — normalize_url
# Copyright Crawl4AI contributors (unclecode/crawl4ai).
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# Extracted verbatim as a single function from crawl4ai/utils.py lines
# 2259-2358; the rest of that file was NOT copied.
# ---------------------------------------------------------------------------

def normalize_url(
    href: str,
    base_url: str,
    *,
    drop_query_tracking=True,
    sort_query=True,
    keep_fragment=False,
    extra_drop_params=None,
    preserve_https=False,
    original_scheme=None
):
    """
    Extended URL normalizer

    Parameters
    ----------
    href : str
        The raw link extracted from a page.
    base_url : str
        The page’s canonical URL (used to resolve relative links).
    drop_query_tracking : bool (default True)
        Remove common tracking query parameters.
    sort_query : bool (default True)
        Alphabetically sort query keys for deterministic output.
    keep_fragment : bool (default False)
        Preserve the hash fragment (#section) if you need in-page links.
    extra_drop_params : Iterable[str] | None
        Additional query keys to strip (case-insensitive).

    Returns
    -------
    str | None
        A clean, canonical URL or None if href is empty/None.
    """
    if not href:
        return None

    # Resolve relative paths first
    full_url = urljoin(base_url, href.strip())
    
    # Preserve HTTPS if requested and original scheme was HTTPS
    if preserve_https and original_scheme == 'https':
        parsed_full = urlparse(full_url)
        parsed_base = urlparse(base_url)
        # Only preserve HTTPS for same-domain links (not protocol-relative URLs)
        # Protocol-relative URLs (//example.com) should follow the base URL's scheme
        if (parsed_full.scheme == 'http' and 
            parsed_full.netloc == parsed_base.netloc and
            not href.strip().startswith('//')):
            full_url = full_url.replace('http://', 'https://', 1)

    # Parse once, edit parts, then rebuild
    parsed = urlparse(full_url)

    # ── netloc ──
    netloc = parsed.netloc.lower()

    # ── path ──
    # Strip duplicate slashes and trailing "/" (except root)
    # IMPORTANT: Don't use quote(unquote()) as it mangles + signs in URLs
    # The path from urlparse is already properly encoded
    path = parsed.path
    # Preserve trailing slashes -- they are semantically significant per RFC 3986
    # e.g. /page/9123/ and /page/9123 may return different responses

    # ── query ──
    query = parsed.query
    if query:
        # explode, mutate, then rebuild
        params = [(k, v) for k, v in parse_qsl(query, keep_blank_values=True)]

        if drop_query_tracking:
            default_tracking = {
                'utm_source', 'utm_medium', 'utm_campaign', 'utm_term',
                'utm_content', 'gclid', 'fbclid', 'ref', 'ref_src'
            }
            if extra_drop_params:
                default_tracking |= {p.lower() for p in extra_drop_params}
            params = [(k, v) for k, v in params if k.lower() not in default_tracking]

        if sort_query:
            params.sort(key=lambda kv: kv[0])

        query = urlencode(params, doseq=True) if params else ''

    # ── fragment ──
    fragment = parsed.fragment if keep_fragment else ''

    # Re-assemble
    normalized = urlunparse((
        parsed.scheme,
        netloc,
        path,
        parsed.params,
        query,
        fragment
    ))

    return normalized
