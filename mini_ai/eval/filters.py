"""Filter pipeline for eval outputs — original code.

Idea rebuilt from the LM-Eval-Harness description in the sweep
(``lm_eval/api/filter.py``: a pipeline of named text transforms
applied to model outputs before scoring). No lm-eval code was read
or copied; the filter names and the pipeline shape are the standard
idea, the implementation here is original.

A filter is a pure ``str -> str`` function. Filters are registered
by name in :data:`FILTER_REGISTRY` and applied in order: the output
of one is the input of the next, so order matters and is part of a
task's definition. A task lists filters either as plain names::

    filters: [strip, lowercase]

or, when a filter needs arguments, as a mapping::

    filters:
      - name: extract_after_marker
        marker: "Answer:"

In Python the same two forms are accepted: a string name, or a
``{"name": ..., <arg>: ...}`` dict. Unknown filter names raise
``KeyError`` at task-load time, not silently mid-run.
"""

__all__ = [
    "FILTER_REGISTRY",
    "FilterRegistry",
    "apply_filters",
    "collapse_whitespace",
    "extract_after_marker",
    "lowercase",
    "register_filter",
    "resolve_filter",
    "strip",
    "take_first_line",
]


def strip(text):
    """Remove leading and trailing whitespace."""
    return text.strip()


def lowercase(text):
    """Lowercase the whole output."""
    return text.lower()


def take_first_line(text):
    """Keep only the first line (split on ``\\n``)."""
    return text.split("\n", 1)[0]


def collapse_whitespace(text):
    """Collapse every run of whitespace to a single space, then strip."""
    return " ".join(text.split())


def extract_after_marker(text, marker="Answer:"):
    """Return the text after the first occurrence of ``marker``.

    If the marker is absent the text is returned unchanged — a
    missing marker is not an error, it just means the model did not
    use the expected format, and the unfiltered text is what gets
    scored (and usually fails exact-match, which is the honest
    outcome). ``marker`` is matched case-sensitively, so filter
    order matters: ``lowercase`` before this filter changes what
    marker will match.
    """
    _, sep, after = text.partition(marker)
    return after if sep else text


class FilterRegistry:
    """A name -> filter-function registry. One global instance exists
    as :data:`FILTER_REGISTRY`; tests may build their own."""

    def __init__(self):
        self._filters = {}

    def register(self, name, func):
        """Register ``func`` under ``name`` (overwrites silently)."""
        if not isinstance(name, str) or not name:
            raise ValueError("filter name must be a non-empty string")
        if not callable(func):
            raise TypeError("filter must be callable")
        self._filters[name] = func
        return func

    def get(self, name):
        """Return the filter registered as ``name`` (KeyError if absent)."""
        try:
            return self._filters[name]
        except KeyError:
            raise KeyError(f"unknown filter: {name!r}") from None

    def __contains__(self, name):
        return name in self._filters

    def list(self):
        """Sorted list of registered filter names."""
        return sorted(self._filters)


FILTER_REGISTRY = FilterRegistry()
FILTER_REGISTRY.register("strip", strip)
FILTER_REGISTRY.register("lowercase", lowercase)
FILTER_REGISTRY.register("take_first_line", take_first_line)
FILTER_REGISTRY.register("collapse_whitespace", collapse_whitespace)
FILTER_REGISTRY.register("extract_after_marker", extract_after_marker)


def register_filter(name, func=None, registry=None):
    """Register ``func`` under ``name`` in ``registry`` (default global).

    Usable as a decorator: ``@register_filter("my_filter")``.
    """
    reg = registry if registry is not None else FILTER_REGISTRY

    def _register(f):
        reg.register(name, f)
        return f

    if func is not None:
        return _register(func)
    return _register


def resolve_filter(spec, registry=None):
    """Turn a filter spec into a ``str -> str`` callable.

    ``spec`` is a plain name (``"strip"``), a dict
    (``{"name": "extract_after_marker", "marker": "Answer:"}``),
    or a ``(name, kwargs-dict)`` tuple. A dict must carry a ``"name"``
    key; every other key is passed as a keyword argument to the
    filter function.
    """
    reg = registry if registry is not None else FILTER_REGISTRY
    if isinstance(spec, str):
        func = reg.get(spec)
        return func
    if isinstance(spec, dict):
        if "name" not in spec:
            raise ValueError(f"filter spec needs a 'name' key: {spec!r}")
        func = reg.get(spec["name"])
        kwargs = {k: v for k, v in spec.items() if k != "name"}
        if not kwargs:
            return func

        def _bound(text, _f=func, _kw=kwargs):
            return _f(text, **_kw)

        return _bound
    if isinstance(spec, tuple) and len(spec) == 2:
        func = reg.get(spec[0])
        kwargs = spec[1] or {}

        def _bound_tuple(text, _f=func, _kw=kwargs):
            return _f(text, **_kw)

        return _bound_tuple
    raise TypeError(f"invalid filter spec: {spec!r}")


def apply_filters(text, specs, registry=None):
    """Apply ``specs`` to ``text`` in order, returning the result.

    ``specs`` is a list of filter specs (see :func:`resolve_filter`).
    An empty list returns ``text`` unchanged. Non-string input raises
    ``TypeError``; a filter returning a non-string raises
    ``TypeError`` too, so a bad filter fails loudly instead of
    scoring garbage.
    """
    if not isinstance(text, str):
        raise TypeError(f"filters apply to text, not {type(text).__name__}")
    result = text
    for spec in specs or []:
        result = resolve_filter(spec, registry=registry)(result)
        if not isinstance(result, str):
            raise TypeError(f"filter {spec!r} did not return a string")
    return result
