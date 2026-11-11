"""Task registry for eval — original code.

Idea rebuilt from the LM-Eval-Harness description in the sweep
(``lm_eval/tasks/``: 227 task directories, mostly YAML task
definitions, plus ``lm_eval/api/registry.py``). No lm-eval code was
read or copied; the shape — a named task defined in YAML, held in a
registry, rendered through a prompt template — is the idea, and
everything here is written from it.

A task definition (YAML or dict) has:

- ``name`` — unique task name (required).
- ``description`` — what the task measures (required).
- ``prompt_template`` — a ``str.format`` template using the item
  fields, e.g. ``"Question: {question}\\nAnswer:"`` (required).
  The ``answer`` field is never passed to the template, so a
  template cannot accidentally leak the reference into the prompt.
- ``items`` — a non-empty list of dicts (required). Every item must
  have an ``answer`` key (the reference, stored in canonical form —
  already stripped/lowercased if the task's filters do that to
  predictions) plus whatever fields the template uses.
- ``metrics`` — metric names from the metric registry
  (default ``["exact_match", "accuracy"]``). Validated at load time.
- ``filters`` — filter specs from the filter registry
  (default ``[]``). Validated at load time.

Task files live in ``mini_ai/eval/tasks/*.yaml`` and are loaded with
:func:`load_task` / :func:`load_builtin_tasks`. The YAML reader is
the original subset parser in :mod:`mini_ai.eval.yaml_subset` —
stdlib only, no PyYAML dependency (see that module for the exact
subset). A task may equally be defined as a plain dict and passed
to :func:`task_from_dict`.
"""

import os

from .filters import FILTER_REGISTRY
from .metrics import METRIC_REGISTRY
from .yaml_subset import parse_yaml_subset

__all__ = [
    "EvalTask",
    "TASK_REGISTRY",
    "TaskRegistry",
    "get_task",
    "list_tasks",
    "load_builtin_tasks",
    "load_task",
    "register_task",
    "task_from_dict",
]

_BUILTIN_TASKS_DIR = os.path.join(os.path.dirname(__file__), "tasks")


class EvalTask:
    """One eval task: template + items + which metrics/filters apply."""

    def __init__(self, name, description, prompt_template, items,
                 metric_names=None, filter_specs=None):
        if not isinstance(name, str) or not name:
            raise ValueError("task name must be a non-empty string")
        if not isinstance(description, str) or not description:
            raise ValueError("task description must be a non-empty string")
        if not isinstance(prompt_template, str) or not prompt_template:
            raise ValueError("task prompt_template must be a non-empty string")
        if not isinstance(items, list) or not items:
            raise ValueError("task items must be a non-empty list")
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValueError(f"task item {i} must be a mapping")
            if "answer" not in item:
                raise ValueError(f"task item {i} is missing the 'answer' key")
            if not isinstance(item["answer"], str):
                raise ValueError(f"task item {i} 'answer' must be a string")
        self.name = name
        self.description = description
        self.prompt_template = prompt_template
        self.items = items
        self.metric_names = list(metric_names) if metric_names is not None else ["exact_match", "accuracy"]
        self.filter_specs = list(filter_specs) if filter_specs is not None else []

    def render_prompt(self, item):
        """Render the prompt for ``item`` (``answer`` never included)."""
        fields = {k: v for k, v in item.items() if k != "answer"}
        try:
            return self.prompt_template.format(**fields)
        except KeyError as exc:
            raise ValueError(
                f"task {self.name!r}: prompt template needs field {exc} "
                f"which item {item!r} does not have"
            ) from None

    def to_dict(self):
        """Plain-dict form of the task definition (JSON-able)."""
        return {
            "name": self.name,
            "description": self.description,
            "prompt_template": self.prompt_template,
            "items": [dict(item) for item in self.items],
            "metrics": list(self.metric_names),
            "filters": list(self.filter_specs),
        }


class TaskRegistry:
    """A name -> EvalTask registry. One global instance exists as
    :data:`TASK_REGISTRY`."""

    def __init__(self):
        self._tasks = {}

    def register(self, task):
        """Register an :class:`EvalTask` (overwrites silently)."""
        if not isinstance(task, EvalTask):
            raise TypeError("only EvalTask instances can be registered")
        self._tasks[task.name] = task
        return task

    def get(self, name):
        """Return the task registered as ``name`` (KeyError if absent)."""
        try:
            return self._tasks[name]
        except KeyError:
            raise KeyError(f"unknown task: {name!r}") from None

    def __contains__(self, name):
        return name in self._tasks

    def list(self):
        """Sorted list of registered task names."""
        return sorted(self._tasks)


TASK_REGISTRY = TaskRegistry()


def register_task(task, registry=None):
    """Register ``task`` in ``registry`` (default global)."""
    reg = registry if registry is not None else TASK_REGISTRY
    return reg.register(task)


def get_task(name, registry=None):
    """Return the task registered as ``name``."""
    reg = registry if registry is not None else TASK_REGISTRY
    return reg.get(name)


def list_tasks(registry=None):
    """Sorted list of registered task names."""
    reg = registry if registry is not None else TASK_REGISTRY
    return reg.list()


def task_from_dict(data, registry=None):
    """Build (and register) an :class:`EvalTask` from a plain dict.

    Validates that every named metric exists in the metric registry
    and every named filter exists in the filter registry, so a task
    that names something unregistered fails at load time with a
    ``KeyError`` naming the missing piece — never mid-run.
    Unknown top-level keys raise ``ValueError``.
    """
    if not isinstance(data, dict):
        raise TypeError("task definition must be a mapping")
    allowed = {"name", "description", "prompt_template", "items", "metrics", "filters"}
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError(f"unknown task keys: {unknown}")
    for field in ("name", "description", "prompt_template", "items"):
        if field not in data:
            raise ValueError(f"task definition is missing required field: {field!r}")
    metric_names = data.get("metrics", ["exact_match", "accuracy"])
    filter_specs = data.get("filters", [])
    for metric_name in metric_names:
        if metric_name not in METRIC_REGISTRY:
            raise KeyError(f"task {data.get('name')!r} names unknown metric: {metric_name!r}")
    for spec in filter_specs:
        spec_name = spec["name"] if isinstance(spec, dict) else spec
        if spec_name not in FILTER_REGISTRY:
            raise KeyError(f"task {data.get('name')!r} names unknown filter: {spec_name!r}")
    task = EvalTask(
        name=data["name"],
        description=data["description"],
        prompt_template=data["prompt_template"],
        items=data["items"],
        metric_names=metric_names,
        filter_specs=filter_specs,
    )
    if registry is not None:
        registry.register(task)
    return task


def load_task(path, registry=None):
    """Load a task from a YAML file at ``path`` and register it.

    The file is parsed by the original YAML-subset parser
    (:mod:`mini_ai.eval.yaml_subset`); see that module for the
    supported subset. Returns the :class:`EvalTask`.
    """
    with open(path, "r", encoding="utf-8") as handle:
        data = parse_yaml_subset(handle.read())
    return task_from_dict(data, registry=registry)


def load_builtin_tasks(registry=None):
    """Load every ``*.yaml`` task shipped in ``mini_ai/eval/tasks/``.

    Returns the list of loaded tasks. Safe to call twice: re-loading
    overwrites the same names in the registry.
    """
    reg = registry if registry is not None else TASK_REGISTRY
    loaded = []
    if not os.path.isdir(_BUILTIN_TASKS_DIR):
        return loaded
    for filename in sorted(os.listdir(_BUILTIN_TASKS_DIR)):
        if filename.endswith(".yaml"):
            loaded.append(load_task(os.path.join(_BUILTIN_TASKS_DIR, filename), registry=reg))
    return loaded
