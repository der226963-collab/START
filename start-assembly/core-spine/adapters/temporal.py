"""Temporal knowledge adapter (Module 6) — original Python, stdlib only.

Design inspiration: Graphiti (getzep/graphiti, Apache-2.0, verified
in the sweep/audit from its own LICENSE file). What was rebuilt
here is ONLY the temporal-edge/episode field schema as original
START code: episodes with validity windows (valid-from /
valid-to), episode links, and a superseded-by link. NO Graphiti
code was copied, and the Graphiti system was NOT adopted: no
graph database (Neo4j default, Kuzu deprecated), no LLM
extraction (every temporal bound in Graphiti is LLM-extracted),
no PostHog telemetry (on by default in Graphiti). Graphiti's
audit finding stands: it has no verified flag and no
needs_human_decision anywhere in graphiti_core, so a retrieved
fact could be treated as verified with no separate check. This
module does the opposite — see the governance rule below.

Semantics (original, defined here, not copied):
- An episode has valid_from / valid_to (valid_to None = still
  current / open-ended), a superseded_by link to the episode
  that replaced it, and episode links (previous / next / part-of)
  as plain JSON-able references (episode ids as strings).
- "Current" at time T means: the validity window covers T AND
  the episode is not superseded. An episode superseded by a
  later one is NEVER returned as current, even if its valid_to
  is still open — supersession closes it.
- Temporal filtering: a query at T returns the episode valid at
  T, not one valid only before or after T. A query outside all
  windows returns an empty list — not an error, not a stale
  record.
- Verified status is separate and never invented: a superseded
  record can NEVER be presented as verified-current, and this
  module NEVER sets verified=true. The verified flag on a record
  comes only from the verify step + human approval (outside this
  module); the temporal layer carries the stored flag unchanged
  through add / query / serialisation. There is no function in
  this module that sets verified.
- Wire format stays JSON: episodes serialise to plain JSON-able
  dicts (schema_version "1.0.0") with licence/provenance fields,
  following the other adapters (model results carry
  verified=false and needs_human_decision=true).

Times are ISO dates ("YYYY-MM-DD"); windows are inclusive on
both ends. All data here is synthetic (a small food-system
knowledge timeline); no real data, no graph database, no LLM.
"""

import json
from datetime import date

SCHEMA_VERSION = "1.0.0"
LICENCE = "Apache-2.0"
PROVENANCE = "START original — Graphiti temporal schema as design inspiration only, no code copied"


def parse_date(value):
    """Parse an ISO date string ("YYYY-MM-DD") or pass a date through.

    Raises ValueError on anything else — a bad timestamp is never
    silently treated as a valid bound.
    """
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError(f"not an ISO date or datetime.date: {value!r}")


class Episode:
    """One temporal knowledge episode.

    valid_to None means the episode is still current (open-ended).
    superseded_by None means no later episode has replaced it.
    links maps a relation name ("previous", "next", "part_of") to
    an episode id (plain string reference, never an object).
    verified is carried unchanged from storage; this module never
    sets it — see the module docstring.
    """

    def __init__(self, episode_id, fact, valid_from, valid_to=None,
                 superseded_by=None, links=None, verified=False,
                 licence=LICENCE, provenance=PROVENANCE, synthetic=True):
        if not episode_id or not isinstance(episode_id, str):
            raise ValueError("episode_id must be a non-empty string")
        self.id = episode_id
        self.fact = fact
        self.valid_from = parse_date(valid_from)
        if valid_to is not None:
            self.valid_to = parse_date(valid_to)
        else:
            self.valid_to = None
        if self.valid_to is not None and self.valid_from > self.valid_to:
            raise ValueError(
                f"invalid window for {episode_id}: valid_from "
                f"{self.valid_from} is after valid_to {self.valid_to}")
        if superseded_by is not None and superseded_by == episode_id:
            raise ValueError(
                f"episode {episode_id} cannot supersede itself")
        self.superseded_by = superseded_by
        self.links = dict(links) if links else {}
        # Carried, never set by this module: the stored flag is kept
        # exactly as supplied. No code path here assigns True.
        self.verified = bool(verified)
        self.licence = licence
        self.provenance = provenance
        self.synthetic = bool(synthetic)

    def is_current(self, at):
        """True iff the window covers `at` AND not superseded.

        Supersession closes the episode even when valid_to is still
        open (None) — a superseded episode is never current.
        """
        at = parse_date(at)
        if self.superseded_by is not None:
            return False
        if at < self.valid_from:
            return False
        if self.valid_to is not None and at > self.valid_to:
            return False
        return True

    def to_dict(self):
        """Plain JSON-able dict. Verified flag carried unchanged."""
        return {
            "schema_version": SCHEMA_VERSION,
            "id": self.id,
            "fact": self.fact,
            "valid_from": self.valid_from.isoformat(),
            "valid_to": (self.valid_to.isoformat()
                         if self.valid_to is not None else None),
            "superseded_by": self.superseded_by,
            "links": dict(self.links),
            "verified": self.verified,
            "licence": self.licence,
            "provenance": self.provenance,
            "synthetic": self.synthetic,
        }

    @classmethod
    def from_dict(cls, data):
        """Rebuild an episode from a dict produced by to_dict()."""
        return cls(
            episode_id=data["id"],
            fact=data["fact"],
            valid_from=data["valid_from"],
            valid_to=data.get("valid_to"),
            superseded_by=data.get("superseded_by"),
            links=data.get("links") or {},
            verified=data.get("verified", False),
            licence=data.get("licence", LICENCE),
            provenance=data.get("provenance", PROVENANCE),
            synthetic=data.get("synthetic", True),
        )


def episode_to_dict(episode):
    """Serialise one episode to a plain JSON-able dict."""
    return episode.to_dict()


def episode_from_dict(data):
    """Deserialise one episode. The verified flag is carried as stored."""
    return Episode.from_dict(data)


class TemporalStore:
    """An in-memory store of episodes. No database, no LLM.

    Episodes are stored by id. Adding a duplicate id, an invalid
    window, or a self-supersession raises ValueError. A
    superseded_by link to an id not (yet) in the store is allowed
    at add time (ingest order) but is reported as UNKNOWN by
    follow_chain() / validate_links() — never silently resolved.
    """

    def __init__(self):
        self._episodes = {}

    def add(self, episode):
        """Add an episode. Duplicate ids are rejected, never merged."""
        if episode.id in self._episodes:
            raise ValueError(f"duplicate episode id: {episode.id!r}")
        self._episodes[episode.id] = episode
        return episode

    def get(self, episode_id):
        """Return the episode with this id, or None."""
        return self._episodes.get(episode_id)

    def supersede(self, old_id, new_id):
        """Record that new_id replaces old_id.

        Both episodes must exist, and old_id must not already be
        superseded. Supersession never touches the verified flag
        of either episode.
        """
        old = self._episodes.get(old_id)
        new = self._episodes.get(new_id)
        if old is None:
            raise ValueError(f"cannot supersede unknown episode: {old_id!r}")
        if new is None:
            raise ValueError(f"replacing episode unknown: {new_id!r}")
        if old_id == new_id:
            raise ValueError("an episode cannot supersede itself")
        if old.superseded_by is not None:
            raise ValueError(
                f"episode {old_id!r} is already superseded by "
                f"{old.superseded_by!r}")
        old.superseded_by = new_id
        return old

    def current(self, at):
        """Episodes current at time `at`: window covers T, not superseded."""
        at = parse_date(at)
        return [ep for ep in self._episodes.values() if ep.is_current(at)]

    def current_verified(self, at):
        """Current episodes whose STORED verified flag is True.

        The flag is only ever read here, never set: a superseded
        episode — even one stored with verified=true — is excluded
        by current(), so it can never appear in this result.
        """
        return [ep for ep in self.current(at) if ep.verified]

    def follow_chain(self, episode_id):
        """Follow superseded_by links to the current episode.

        Returns (episode, status, reason): status "current" with
        the current episode, or "unknown" with episode None when
        the chain is broken (a link to a non-existent id), the
        starting id is unknown, or the chain cycles. A broken
        chain is never silently resolved to a current record.
        """
        seen = set()
        current_id = episode_id
        while True:
            if current_id in seen:
                return (None, "unknown",
                        f"superseded_by cycle at {current_id!r}: "
                        f"chain {' -> '.join(sorted(seen))} repeats")
            seen.add(current_id)
            episode = self._episodes.get(current_id)
            if episode is None:
                return (None, "unknown",
                        f"superseded_by link to unknown episode "
                        f"{current_id!r}")
            if episode.superseded_by is None:
                return (episode, "current",
                        f"chain ends at current episode {current_id!r}")
            current_id = episode.superseded_by

    def validate_links(self):
        """List broken superseded_by links (and self-links, if any).

        Returns a list of dicts {"from": id, "to": id, "problem":
        ...}; empty means every superseded_by link resolves.
        """
        broken = []
        for episode in self._episodes.values():
            target = episode.superseded_by
            if target is None:
                continue
            if target == episode.id:
                broken.append({"from": episode.id, "to": target,
                               "problem": "self-supersession"})
            elif target not in self._episodes:
                broken.append({"from": episode.id, "to": target,
                               "problem": "target episode does not exist"})
        return broken

    def to_dict(self):
        """Whole store as a plain JSON-able dict."""
        return {
            "schema_version": SCHEMA_VERSION,
            "licence": LICENCE,
            "provenance": PROVENANCE,
            "synthetic": True,
            "episodes": [ep.to_dict()
                         for ep in self._episodes.values()],
        }

    @classmethod
    def from_dict(cls, data):
        """Rebuild a store from to_dict() output. Flags carried as stored."""
        store = cls()
        for ep_data in data.get("episodes", []):
            store.add(Episode.from_dict(ep_data))
        return store


def query_current(store, at, verified_only=False):
    """Query current knowledge at time `at`, as a JSON-able result.

    Returns {"episodes": [...], "count": n, "status": "ok",
    "verified": false, "needs_human_decision": true}. The result
    itself is unverified model output: it must still go through
    the separate verify step like any other model output, and
    verified_only only filters on the STORED verified flag — it
    never creates a verified record.
    """
    episodes = (store.current_verified(at) if verified_only
                else store.current(at))
    return {
        "schema_version": SCHEMA_VERSION,
        "query_time": parse_date(at).isoformat(),
        "verified_only": bool(verified_only),
        "episodes": [ep.to_dict() for ep in episodes],
        "count": len(episodes),
        "status": "ok",
        "verified": False,
        "needs_human_decision": True,
    }


def store_to_json(store):
    """Serialise a store to a JSON string."""
    return json.dumps(store.to_dict(), sort_keys=True)


def store_from_json(text):
    """Deserialise a store from a JSON string. Flags carried as stored."""
    return TemporalStore.from_dict(json.loads(text))


# Synthetic knowledge timeline (clearly synthetic, not real data):
# wheat-yield knowledge revised mid-2026; potato-yield knowledge
# revised with the OLD record stored as verified (to prove a
# superseded verified record is still never current); water
# allocation known per calendar year.
def synthetic_store():
    """Build the synthetic example store used by the tests."""
    store = TemporalStore()
    store.add(Episode(
        "ep-wheat-2026a", "Wheat yield 4.0 t/ha",
        "2026-01-01", "2026-06-30",
        superseded_by="ep-wheat-2026b",
        links={"next": "ep-wheat-2026b"},
        verified=False))
    store.add(Episode(
        "ep-wheat-2026b", "Wheat yield 4.2 t/ha",
        "2026-07-01", None,
        links={"previous": "ep-wheat-2026a"},
        verified=False))
    store.add(Episode(
        "ep-potato-old", "Potato yield 18 t/ha",
        "2026-01-01", "2026-12-31",
        superseded_by="ep-potato-new",
        links={"next": "ep-potato-new"},
        # Stored as verified BEFORE it was superseded — the temporal
        # layer must still never return it as current or verified.
        verified=True))
    store.add(Episode(
        "ep-potato-new", "Potato yield 20 t/ha",
        "2026-01-01", None,
        links={"previous": "ep-potato-old"},
        verified=False))
    store.add(Episode(
        "ep-water-2026", "Water allocation 100,000 m3",
        "2026-01-01", "2026-12-31",
        verified=False))
    store.add(Episode(
        "ep-water-2027", "Water allocation 120,000 m3",
        "2027-01-01", "2027-12-31",
        links={"previous": "ep-water-2026"},
        verified=False))
    return store
