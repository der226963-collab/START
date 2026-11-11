"""Eval task/metric/filter registries — original code, rebuilt from the
LM-Eval-Harness idea (see the sweep:
``start-assembly/core-spine/source-audit/ALL_CANDIDATES_BORROWING_PLAN.md``,
top INSPIRATION-REBUILD item 1 — EleutherAI/lm-evaluation-harness,
MIT, 107,463 lines, task registry of YAML task definitions plus a
metric registry and a filter pipeline).

No lm-eval code was read or copied and there is no lm-eval
dependency: only the design shape was rebuilt, as original Python,
in this package. No paid API, no model backend — a scorer is a
caller-supplied callable, and in tests it is a stub.

Governance: every run result carries ``needs_human_decision=True``
and ``verified=False``. Eval scores are model results, never
verified plans, and nothing here bypasses the verify step.
"""

from .filters import (
    FILTER_REGISTRY,
    FilterRegistry,
    apply_filters,
    collapse_whitespace,
    extract_after_marker,
    lowercase,
    register_filter,
    resolve_filter,
    strip,
    take_first_line,
)
from .metrics import (
    METRIC_REGISTRY,
    MetricRegistry,
    accuracy,
    exact_match,
    perplexity,
    register_metric,
)
from .runner import results_to_json, run_task, run_task_by_name
from .tasks import (
    TASK_REGISTRY,
    EvalTask,
    TaskRegistry,
    get_task,
    list_tasks,
    load_builtin_tasks,
    load_task,
    register_task,
    task_from_dict,
)
from .yaml_subset import YamlSubsetError, parse_yaml_subset

__all__ = [
    "EvalTask",
    "FILTER_REGISTRY",
    "FilterRegistry",
    "METRIC_REGISTRY",
    "MetricRegistry",
    "TASK_REGISTRY",
    "TaskRegistry",
    "YamlSubsetError",
    "accuracy",
    "apply_filters",
    "collapse_whitespace",
    "exact_match",
    "extract_after_marker",
    "get_task",
    "list_tasks",
    "load_builtin_tasks",
    "load_task",
    "lowercase",
    "parse_yaml_subset",
    "perplexity",
    "register_filter",
    "register_metric",
    "register_task",
    "resolve_filter",
    "results_to_json",
    "run_task",
    "run_task_by_name",
    "strip",
    "take_first_line",
    "task_from_dict",
]
