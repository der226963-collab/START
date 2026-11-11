"""Mechanism simulation over immutable graph state (Module 19) —
original Python, stdlib only.

Design inspiration: Collective-Intelligence-Library
(eq-network/Collective-Intelligence-Library, MIT — verified in
the sweep from the repo's own LICENSE file, Copyright (c) 2026
Jonas Hallgren; 21,348 lines of JAX-native Python). The sweep's
verdict for it was INSPIRATION-REBUILD: rebuild effect-declared
pure transforms over immutable graph state as original Python
(JAX-free), results unverified until the verify step. **No
Collective-Intelligence-Library code was copied** — this module
was written from the design idea only (state as an immutable
graph, every step a pure function, each transform declaring
its reads/writes, a pipeline compiled from the read/write DAG).
The library itself was NOT adopted as a dependency: JAX would
be a new heavy dependency for a peripheral module, and the
codebase is very new and unproven (7 stars, single maintainer).
Nothing was installed: no new dependency, ``requirements.txt``
unchanged. No network, no real data — synthetic test data only.

Semantics (original, defined here, not copied):
- ``GraphState`` is immutable by construction. It holds nodes
  (each with a preference and a weight), edges (directed pairs,
  carried through unchanged by the mechanisms here), and a
  globals map. Construction deep-copies its inputs, every
  accessor returns a deep copy, and there is no mutating
  method at all — a transform can only build a *new*
  ``GraphState`` from a modified deep copy of the old one's
  data. ``to_json()`` is the canonical serialisation (sorted
  keys), so "unchanged" is checkable byte-for-byte: run a
  step, and the input state's ``to_json()`` is identical
  afterwards. Equality and hashing are defined on that
  canonical JSON.
- A ``Transform`` is a pure function ``GraphState -> GraphState``
  plus a declared effect: ``reads`` and ``writes`` are field
  paths such as ``"nodes"``, ``"edges"`` or ``"globals.tally"``.
  The function receives the state and must return a new one;
  it is never handed a mutable view of the caller's state.
- ``compile_pipeline(transforms)`` derives execution order
  from the read/write DAG: if transform B reads a field that
  transform A writes, A runs before B. Among transforms that
  are ready at the same time, order is alphabetical by name,
  so compilation is deterministic regardless of the order the
  transforms were listed in. Compilation rejects a write
  conflict (two transforms writing the same field) and a
  cycle (A reads what B writes while B reads what A writes)
  with ``ValueError`` — both are errors at compile time, never
  silently resolved at run time.
- The built-in mechanism is a one-round plurality vote /
  aggregation over a tiny graph, in three transforms:
  ``tally_preferences`` (reads ``nodes``, writes
  ``globals.tally`` — weighted count of each preference),
  ``compute_shares`` (reads ``globals.tally``, writes
  ``globals.shares`` — each tally divided by the total
  weight), ``aggregate_outcome`` (reads ``globals.tally``,
  writes ``globals.outcome`` and ``globals.tied`` — the
  plurality winner; ties are broken by taking the
  lexicographically smallest option name, so the outcome is
  deterministic). ``plurality_pipeline()`` compiles exactly
  these three, in DAG order.
- Every result this module produces carries
  ``verified=false`` and ``needs_human_decision=true``.
  Outputs are model results, never verified plans: they must
  still go through START's separate verify step and human
  approval like any other model output. No function in this
  module sets verified True, and there is no way for a
  transform to promote a result — the flags are set by
  ``run_pipeline()`` on the result envelope, not by any
  transform, and transforms never see or touch them.

Wire format stays JSON: states, pipeline results and the
run record are plain JSON-able dicts (schema_version "1.0.0").
All data here is synthetic; no real collective-intelligence
data, no JAX, no GPU.
"""

import copy
import json

SCHEMA_VERSION = "1.0.0"
LICENCE = "MIT"
PROVENANCE = ("START original — Collective-Intelligence-Library "
              "pure-transform / immutable-graph design as "
              "inspiration only, no code copied")


def _canonical(data):
    """Canonical JSON for a state/result dict (sorted keys)."""
    return json.dumps(data, sort_keys=True)


def _validate_nodes(nodes):
    """Validate a nodes map; raises ValueError on bad input."""
    if not isinstance(nodes, dict):
        raise ValueError("nodes must be a dict of node id -> attributes")
    for node_id, attrs in nodes.items():
        if not isinstance(node_id, str) or not node_id:
            raise ValueError("node ids must be non-empty strings")
        if not isinstance(attrs, dict):
            raise ValueError(f"node {node_id!r} attributes must be a dict")
        pref = attrs.get("preference")
        if not isinstance(pref, str) or not pref:
            raise ValueError(
                f"node {node_id!r} preference must be a non-empty string")
        weight = attrs.get("weight", 1)
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise ValueError(
                f"node {node_id!r} weight must be a number")
        if weight <= 0:
            raise ValueError(
                f"node {node_id!r} weight must be positive, got {weight!r}")
        extra = set(attrs) - {"preference", "weight"}
        if extra:
            raise ValueError(
                f"node {node_id!r} has unknown attributes: {sorted(extra)}")


def _validate_edges(edges):
    if not isinstance(edges, list):
        raise ValueError("edges must be a list of [from, to] pairs")
    for edge in edges:
        if (not isinstance(edge, (list, tuple)) or len(edge) != 2
                or not all(isinstance(e, str) and e for e in edge)):
            raise ValueError(
                f"each edge must be a [from, to] pair of non-empty "
                f"strings, got {edge!r}")


class GraphState:
    """An immutable graph state: nodes, edges, globals.

    Construction deep-copies its inputs, so later mutation of
    a caller's dict cannot change the state, and no method
    mutates the state in place. ``with_globals()`` and
    ``with_nodes()`` return *new* states. Accessors return deep
    copies, so a caller mutating what it got back cannot change
    the state either.
    """

    def __init__(self, nodes=None, edges=None, globals_=None):
        nodes = copy.deepcopy(nodes) if nodes is not None else {}
        edges = copy.deepcopy(edges) if edges is not None else []
        globals_ = copy.deepcopy(globals_) if globals_ is not None else {}
        _validate_nodes(nodes)
        _validate_edges(edges)
        if not isinstance(globals_, dict):
            raise ValueError("globals must be a dict")
        # Normalise edges to lists so the canonical JSON is stable.
        edges = [list(e) for e in edges]
        self._data = {
            "schema_version": SCHEMA_VERSION,
            "nodes": nodes,
            "edges": edges,
            "globals": globals_,
        }

    # -- read-only access (deep copies only) ---------------------------

    def nodes(self):
        """A deep copy of the nodes map."""
        return copy.deepcopy(self._data["nodes"])

    def edges(self):
        """A deep copy of the edge list."""
        return copy.deepcopy(self._data["edges"])

    def globals(self):
        """A deep copy of the globals map."""
        return copy.deepcopy(self._data["globals"])

    def to_dict(self):
        """A deep copy of the whole state as a plain dict."""
        return copy.deepcopy(self._data)

    def to_json(self):
        """Canonical JSON (sorted keys) — the byte-level identity."""
        return _canonical(self._data)

    @classmethod
    def from_dict(cls, data):
        """Rebuild a state from a plain dict (deep-copied)."""
        if not isinstance(data, dict):
            raise ValueError("state data must be a dict")
        return cls(nodes=data.get("nodes", {}),
                   edges=data.get("edges", []),
                   globals_=data.get("globals", {}))

    @classmethod
    def from_json(cls, text):
        """Rebuild a state from its canonical JSON."""
        return cls.from_dict(json.loads(text))

    # -- pure updates: each returns a NEW state -------------------------

    def with_globals(self, updates):
        """A new state with ``updates`` merged into globals.

        ``updates`` must be a dict; the old state's globals are
        untouched (the merge is onto a deep copy).
        """
        if not isinstance(updates, dict):
            raise ValueError("globals updates must be a dict")
        new_globals = copy.deepcopy(self._data["globals"])
        new_globals.update(copy.deepcopy(updates))
        return GraphState(nodes=self._data["nodes"],
                          edges=self._data["edges"],
                          globals_=new_globals)

    def with_nodes(self, nodes):
        """A new state with the nodes map replaced."""
        return GraphState(nodes=nodes,
                          edges=self._data["edges"],
                          globals_=self._data["globals"])

    # -- identity ---------------------------------------------------------

    def __eq__(self, other):
        return isinstance(other, GraphState) and \
            self._data == other._data

    def __hash__(self):
        return hash(self.to_json())

    def __repr__(self):
        return (f"GraphState(nodes={sorted(self._data['nodes'])}, "
                f"edges={len(self._data['edges'])}, "
                f"globals={sorted(self._data['globals'])})")


class Transform:
    """A pure transform: a function plus its declared effect.

    ``reads`` / ``writes`` are field paths (``"nodes"``,
    ``"edges"``, or ``"globals.<key>"``). ``fn`` takes a
    ``GraphState`` and returns a *new* ``GraphState``; it must
    not mutate its input (it cannot — the state has no mutating
    methods — but a transform that returns its input unchanged
    is also legal: it is then a no-op step).
    """

    def __init__(self, name, reads, writes, fn):
        if not name or not isinstance(name, str):
            raise ValueError("transform name must be a non-empty string")
        if not callable(fn):
            raise TypeError("transform fn must be callable")
        self.name = name
        self.reads = tuple(reads)
        self.writes = tuple(writes)
        self.fn = fn

    def __call__(self, state):
        """Apply the transform; returns a new GraphState."""
        if not isinstance(state, GraphState):
            raise ValueError("transform input must be a GraphState")
        result = self.fn(state)
        if not isinstance(result, GraphState):
            raise ValueError(
                f"transform {self.name!r} must return a GraphState")
        return result

    def __repr__(self):
        return (f"Transform({self.name!r}, reads={list(self.reads)}, "
                f"writes={list(self.writes)})")


def compile_pipeline(transforms):
    """Compile transforms into DAG order.

    Returns the transforms in execution order: a transform
    runs after every transform that writes a field it reads.
    Among transforms ready at the same time, order is
    alphabetical by name (deterministic, independent of the
    order the transforms were listed in). Raises ValueError
    on a write conflict (two transforms writing the same
    field), on a duplicate transform name, or on a cycle.
    """
    transforms = list(transforms)
    names = [t.name for t in transforms]
    if len(set(names)) != len(names):
        raise ValueError("duplicate transform names in pipeline")
    writer = {}
    for t in transforms:
        for field in t.writes:
            if field in writer:
                raise ValueError(
                    f"write conflict: {writer[field]!r} and {t.name!r} "
                    f"both write {field!r}")
            writer[field] = t.name
    by_name = {t.name: t for t in transforms}
    # Dependency edges: writer -> reader, for each read field.
    deps = {t.name: set() for t in transforms}
    for t in transforms:
        for field in t.reads:
            if field in writer and writer[field] != t.name:
                deps[t.name].add(writer[field])
    # Kahn's algorithm, ready set kept sorted by name.
    order = []
    remaining = dict(deps)
    while remaining:
        ready = sorted(n for n, d in remaining.items() if not d)
        if not ready:
            raise ValueError(
                "cycle in transform read/write DAG: "
                f"{sorted(remaining)}")
        nxt = ready[0]
        order.append(by_name[nxt])
        del remaining[nxt]
        for d in remaining.values():
            d.discard(nxt)
    return order


def run_pipeline(state, transforms):
    """Run a compiled pipeline over ``state``; returns a result.

    ``state`` is never mutated (each step returns a new state).
    The result envelope is a plain JSON-able dict carrying the
    final state, the step order actually run, and the
    governance flags: ``verified=false`` and
    ``needs_human_decision=true`` on every result. The flags
    are set here, on the envelope — no transform sets them,
    and no transform can change them.
    """
    if not isinstance(state, GraphState):
        raise ValueError("pipeline input must be a GraphState")
    ordered = compile_pipeline(transforms)
    current = state
    steps = []
    for t in ordered:
        current = t(current)
        steps.append(t.name)
    result = {
        "schema_version": SCHEMA_VERSION,
        "mechanism": "plurality-vote",
        "steps": steps,
        "state": current.to_dict(),
        "licence": LICENCE,
        "provenance": PROVENANCE,
        "verified": False,
        "needs_human_decision": True,
        "synthetic": True,
    }
    json.dumps(result)  # must be plain JSON-able, or raise here
    return result


def result_to_json(result):
    """Serialise a pipeline result to a JSON string."""
    return json.dumps(result, sort_keys=True)


def result_from_json(text):
    """Deserialise a pipeline result. Flags carried as stored."""
    return json.loads(text)


# -- the plurality-vote mechanism (three pure transforms) ---------------

def _tally(state):
    """Weighted count of each preference over the nodes."""
    tally = {}
    for attrs in state.nodes().values():
        pref = attrs["preference"]
        tally[pref] = tally.get(pref, 0) + attrs.get("weight", 1)
    # Sorted keys so the canonical JSON is stable.
    return state.with_globals({"tally": {k: tally[k] for k in sorted(tally)}})


def _shares(state):
    """Each tally divided by the total weight."""
    tally = state.globals().get("tally", {})
    total = sum(tally.values())
    if total <= 0:
        shares = {}
    else:
        shares = {k: tally[k] / total for k in sorted(tally)}
    return state.with_globals({"shares": shares})


def _outcome(state):
    """Plurality winner; ties broken by lexicographically smallest name."""
    tally = state.globals().get("tally", {})
    if not tally:
        return state.with_globals({"outcome": None, "tied": []})
    best = max(tally.values())
    tied = sorted(k for k, v in tally.items() if v == best)
    return state.with_globals({"outcome": tied[0], "tied": tied})


tally_preferences = Transform(
    "tally_preferences", reads=("nodes",),
    writes=("globals.tally",), fn=_tally)
compute_shares = Transform(
    "compute_shares", reads=("globals.tally",),
    writes=("globals.shares",), fn=_shares)
aggregate_outcome = Transform(
    "aggregate_outcome", reads=("globals.tally",),
    writes=("globals.outcome", "globals.tied"), fn=_outcome)


def plurality_pipeline():
    """The three plurality-vote transforms, compiled in DAG order."""
    return compile_pipeline(
        [aggregate_outcome, compute_shares, tally_preferences])


def synthetic_state():
    """A tiny synthetic graph: 5 nodes voting on a crop.

    Hand-computed case: wheat 3 (n1, n2, n5), rice 2 (n3, n4)
    — tally {"rice": 2, "wheat": 3}, shares rice 0.4 / wheat
    0.6, winner "wheat". Edges are present only to show the
    graph shape is carried through unchanged.
    """
    return GraphState(
        nodes={
            "n1": {"preference": "wheat", "weight": 1},
            "n2": {"preference": "wheat", "weight": 1},
            "n3": {"preference": "rice", "weight": 1},
            "n4": {"preference": "rice", "weight": 1},
            "n5": {"preference": "wheat", "weight": 1},
        },
        edges=[["n1", "n2"], ["n2", "n3"], ["n3", "n4"], ["n4", "n5"]],
        globals_={})
