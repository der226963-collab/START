"""Safe, propose-and-approve data fetching for the training corpus.

This module is the ONLY place in the project that is allowed to
fetch text from the internet, and it is deliberately narrow:

  1. Allowlist only. A URL is fetched only if its host is in
     ALLOWED_HOSTS and its scheme is https. There is no
     allowlist-override argument anywhere in the public API, so
     a model calling this code cannot widen the list from inside
     a proposal. A human changes ALLOWED_HOSTS by editing this
     file directly, in an editor, with a commit message.
  2. Licence must be stated, and must be in ALLOWED_LICENCES.
     The fetcher does NOT infer a licence from a page. The
     proposer states it, the human reviewer checks it before
     approval, and the licence is stored in the provenance
     record that travels with the file.
  3. Staging only. propose_fetch() writes to
     data/expanded/staging/ and to nothing else. It never
     writes to the training corpus, never trains a model, and
     never pushes anything.
  4. Human approval is the gate. approve_fetch() moves a staged
     file into data/expanded/ only when approved=True is passed
     explicitly from outside the model — the same pattern as
     self_edit.apply_edit(). The default is False, so a bare
     call from a model does nothing except raise.
  5. Audit. Every proposal and approval appends one JSON line
     to data/expanded/staging/fetch_audit.jsonl. That file is
     append-only from this module and is protected from
     self-editing (see mini_ai/self_edit.py PROTECTED).

What this module does NOT do, by design:
  - It does not fetch from arbitrary sites, search engines, or
    social media, and it does not follow a redirect to a host
    outside the allowlist.
  - It does not strip a licence notice, and it does not claim
    a licence the source does not have.
  - It does not check for personal data by itself. That check
    is a human review step before approval: the reviewer must
    confirm the staged text contains no personal data, no
    real-community data, and no copyrighted text beyond its
    stated licence, before calling approve_fetch().
  - It cannot edit itself, SAFETY.md, APPROVAL_POLICY.md, or
    this module's tests. Those files are protected from
    self-editing, and a human edits them directly.

Size limits: at most MAX_BYTES per fetch, at most
MAX_CHARS kept after cleaning. Larger responses are refused,
not truncated silently, so a reviewer is not misled about
what was actually fetched.

This matches PCAC's safety charter: corrigibility first,
human assemblies as decider, transparency (a provenance
record is an audit trail), and no self-modification of the
approval path itself.
"""
import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ALLOWED_HOSTS = {
    "www.gutenberg.org",
    "gutenberg.org",
    "en.wikipedia.org",
    "openstax.org",
    "assets.openstax.org",
    "www.nasa.gov",
    "nasa.gov",
    "www.noaa.gov",
    "noaa.gov",
    "www.climate.gov",
    "climate.gov",
    "github.com",
    "raw.githubusercontent.com",
}

ALLOWED_LICENCES = {
    "Public domain (US)",
    "CC BY 4.0",
    "CC BY 2.5 CA",
    "CC BY-SA 4.0",
    "CC BY-SA 3.0",
    "CC BY-NC-SA 4.0",
}

MAX_BYTES = 5_000_000
MAX_CHARS = 2_000_000
USER_AGENT = "START-training-corpus-fetcher/1.0 (propose-and-approve; human review required)"

_GUTENBERG_START = re.compile(r"\*\*\* START OF (THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*", re.S)
_GUTENBERG_END = re.compile(r"\*\*\* END OF (THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*", re.S)
_TAG = re.compile(r"<script.*?</script>|<style.*?</style>|<[^>]+>", re.S | re.I)


class FetchError(ValueError):
    pass


def _check_url(url):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise FetchError(f"Only https URLs may be fetched, not {parsed.scheme!r}")
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise FetchError(f"Host not in allowlist: {host}")
    return host


def _check_licence(licence):
    if licence not in ALLOWED_LICENCES:
        raise FetchError(
            f"Licence not allowed: {licence!r}. Allowed: {sorted(ALLOWED_LICENCES)}"
        )


def _safe_name(url):
    path = urllib.parse.urlparse(url).path.rstrip("/")
    stem = Path(path).stem or "download"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem)[:80]
    return stem + ".txt"


def clean_text(text, url=""):
    """Strip Gutenberg headers/footers and, for HTML, strip tags.

    This is a cleaning step, not a licence step: it never removes
    a licence notice that is part of the book's own text, and it
    never invents content. Plain text is returned unchanged apart
    from Gutenberg header/footer removal and trimming.
    """
    m = _GUTENBERG_START.search(text)
    if m:
        text = text[m.end():]
    m = _GUTENBERG_END.search(text)
    if m:
        text = text[:m.start()]
    if "<" in text and ">" in text and ("<html" in text.lower() or "<body" in text.lower()):
        text = _TAG.sub(" ", text)
        text = html.unescape(text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip() + "\n"


def _download(url):
    """Fetch one URL, refusing oversize responses and off-allowlist redirects."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            final = resp.geturl()
            _check_url(final)  # redirect must stay on the allowlist
            raw = resp.read(MAX_BYTES + 1)
    except urllib.error.URLError as exc:
        raise FetchError(f"Download failed for {url}: {exc}") from exc
    if len(raw) > MAX_BYTES:
        raise FetchError(f"Response over {MAX_BYTES} bytes, refused, not truncated: {url}")
    return raw.decode("utf-8", errors="replace")


def _append_audit(staging_dir, entry):
    entry = dict(entry)
    entry["time"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with (Path(staging_dir) / "fetch_audit.jsonl").open("a") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")


def propose_fetch(url, licence, title, staging_dir, _download_fn=None):
    """Download one URL into staging. Writes nothing to the training corpus.

    Returns a dict with the staged filename, character count, and
    SHA-256 of the cleaned text. The human reviewer must check the
    licence, the source, and that the text contains no personal
    data, before calling approve_fetch().
    """
    _check_url(url)
    _check_licence(licence)
    download = _download_fn or _download
    text = clean_text(download(url), url)
    if len(text) > MAX_CHARS:
        raise FetchError(f"Cleaned text over {MAX_CHARS} characters, refused: {url}")
    if len(text) < 100:
        raise FetchError(f"Fetched text suspiciously short ({len(text)} chars): {url}")
    staging_dir = Path(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)
    name = _safe_name(url)
    staged = staging_dir / name
    if staged.exists():
        raise FetchError(f"Staged file already exists, refusing to overwrite: {name}")
    staged.write_text(text)
    provenance = {
        "title": title,
        "url": url,
        "licence": licence,
        "staged_file": name,
        "chars": len(text),
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "status": "proposed",
        "approved": False,
    }
    (staging_dir / (name + ".json")).write_text(json.dumps(provenance, indent=2))
    _append_audit(staging_dir, {"action": "propose", **provenance})
    return provenance


def approve_fetch(staged_name, staging_dir, expanded_dir, approved=False):
    """Move a staged file into data/expanded/, only with human approval.

    approved must be passed explicitly by a human (or human-approved
    tooling outside the model). The default is False, so a bare call
    from a model does nothing except raise. The provenance record
    is updated to approved=True and the move is audited.
    """
    if not approved:
        raise FetchError(
            "Fetch not approved: approved=False. A human must review "
            "the staged text, its licence, and its provenance, and "
            "approve it before it enters the training corpus."
        )
    staging_dir = Path(staging_dir)
    expanded_dir = Path(expanded_dir)
    staged = staging_dir / staged_name
    if staged.suffix != ".txt" or ".." in Path(staged_name).parts:
        raise FetchError(f"Refusing unsafe staged name: {staged_name!r}")
    if not staged.exists():
        raise FetchError(f"No staged file: {staged_name}")
    expanded_dir.mkdir(parents=True, exist_ok=True)
    target = expanded_dir / staged_name
    if target.exists():
        raise FetchError(f"Expanded file already exists, refusing to overwrite: {staged_name}")
    text = staged.read_text()
    target.write_text(text)
    prov_path = staging_dir / (staged_name + ".json")
    provenance = json.loads(prov_path.read_text()) if prov_path.exists() else {}
    provenance.update({"status": "approved", "approved": True})
    (expanded_dir / (staged_name + ".json")).write_text(json.dumps(provenance, indent=2))
    staged.unlink()
    prov_path.unlink(missing_ok=True)
    _append_audit(staging_dir, {"action": "approve", **provenance})
    return provenance


def list_staged(staging_dir):
    """List staged proposals with their provenance, for human review."""
    staging_dir = Path(staging_dir)
    out = []
    for prov_path in sorted(staging_dir.glob("*.json")):
        if prov_path.name == "fetch_audit.jsonl":
            continue
        try:
            out.append(json.loads(prov_path.read_text()))
        except (json.JSONDecodeError, OSError):
            continue
    return out


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Propose-and-approve data fetching. See module docstring.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("propose")
    p.add_argument("--url", required=True)
    p.add_argument("--licence", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--staging-dir", default="data/expanded/staging")
    a = sub.add_parser("approve")
    a.add_argument("--file", required=True, help="Staged filename, e.g. 2009.txt")
    a.add_argument("--staging-dir", default="data/expanded/staging")
    a.add_argument("--expanded-dir", default="data/expanded")
    a.add_argument("--approved", action="store_true",
                   help="Human approval flag. Without it, nothing is moved.")
    sub.add_parser("list").add_argument("--staging-dir", default="data/expanded/staging")
    args = parser.parse_args()
    if args.cmd == "propose":
        print(json.dumps(propose_fetch(args.url, args.licence, args.title, args.staging_dir), indent=2))
    elif args.cmd == "approve":
        print(json.dumps(approve_fetch(args.file, args.staging_dir, args.expanded_dir,
                                       approved=args.approved), indent=2))
    else:
        print(json.dumps(list_staged(args.staging_dir), indent=2))
