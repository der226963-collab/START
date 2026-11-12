# AI Starter — a small, local, auditable beginning

It is a minimal AI you can actually read, train, and change:

1. A tiny neural network written from scratch in NumPy (`mini_ai/neural_net.py`)
   — one hidden layer, ReLU, softmax, manual back-propagation.
2. A tiny intent classifier on top of it (`mini_ai/assistant.py`)
   — it learns a handful of intents from a few example sentences each.
3. A command-line chat loop (`main.py`) — type, get a response, type `quit`.

## Run it

```bash
cd ai-starter
pip install -r requirements.txt
python main.py
```

Try: `hello`, `can you help me plan something?`, `thanks`, `bye`

## Run the tests

```bash
python -m unittest discover -s tests
# Planning tests are plain functions, run them by import:
python -c "import importlib.util; s=importlib.util.spec_from_file_location('t','tests/test_planning.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); [getattr(m,f)() for f in dir(m) if f.startswith('test_')]"
```

## Step 2 — MiniGPT: a larger model that generates text

v1 classified a sentence. MiniGPT (`mini_ai/gpt/`) predicts the
next character, which is how a language model actually works:

- Token + position embeddings, then stacked pre-norm transformer
  blocks: causal multi-head self-attention, then a 4x feed-forward
  network, with residual connections around both.
- Default tiny config: 2 layers, 64-dim, ~100k parameters — small
  enough to train on a CPU in minutes.
- `small` config: 4 layers, 128-dim, ~800k parameters.

```bash
pip install -r requirements-gpt.txt   # PyTorch, CPU build is fine
python train_gpt.py                   # tiny, 500 steps by default
python train_gpt.py --size small --steps 2000
python generate_gpt.py --prompt "The garden " --length 200
```

Training now uses a 90/10 train / validation split, cosine
learning-rate decay, gradient clipping, and saves the best
validation checkpoint — not just the last step. The checkpoint
JSON records the corpus file, its SHA-256, seed, config, and
losses, so a model can be traced back to its exact training text.
New: `--data-dir data` trains on all ideal-model text files with
per-file provenance, `--dropout` regularises larger runs, and
`evaluate_gpt.py` reports loss and perplexity on any held-out file.

The planning layer now also has `check_plan_limits()` — a plan
is checked against stored boundaries (phosphorus, food need,
48-hour work threshold) and anything without a stored boundary
is reported as unknown, not passed — and `backtest_climate()`,
which fits a linear trend to 1999 and tests it on 2000-2025 as
a baseline any fancier predictive model must beat.

## General-agent foundations — not AGI

This is the beginning of a more general model, not AGI, which
has not been achieved. The foundations, all original code
inspired by published patterns (ReAct, Yao et al. 2022;
retrieval-augmented generation; Alpaca instruction format;
RMSNorm, RoPE, SwiGLU modern transformer recipe):

- `mini_ai/agent.py` — a ReAct loop: retrieve first, call a
  planning tool, observe, self-critique, then answer with
  `needs_human_decision=True`. It cannot decide, allocate,
  edit files, or spend anything. Run it with:
  `python -m mini_ai.agent "What is the phosphorus limit?"`
- `mini_ai/gpt/model_modern.py` — a modern transformer variant
  (RMSNorm, RoPE, SwiGLU) to compare with the classic model.
  Train it with `train_gpt.py --modern --data-dir data`.
- `data/instructions.txt` — Alpaca-style instruction/response
  pairs, original text, for instruction-following training.
- `tests/test_general.py` — the agent and modern model tests.
  A scaffold that routes to the wrong tool, or claims AGI, fails.

Guardrails are unchanged: planning stays separate from language,
decisions stay with human assemblies, and self-edit protections
still apply.

## mini_ai/eval — task/metric registry (Module 3, rebuilt from lm-eval inspiration)

The top INSPIRATION-REBUILD item from the 70-candidate borrowing
sweep (see `start-assembly/core-spine/source-audit/
ALL_CANDIDATES_BORROWING_PLAN.md`, item 1): LM-Eval-Harness
(EleutherAI/lm-evaluation-harness, MIT, 107,463 lines) is an
evaluation framework whose real value for START is its design — a
task registry of YAML-defined eval tasks, a metric registry, and a
filter pipeline. It was NOT adopted as a dependency (107k lines for
a job `evaluate_gpt.py` already does in miniature, and it has no
adapter for a from-scratch toy model). Instead the idea was rebuilt
as original Python in `mini_ai/eval/`. No lm-eval code was read or
copied, there is no lm-eval dependency, and there is no paid API —
a scorer is a caller-supplied callable, and in tests it is a stub.

File layout (all original code, stdlib only — no new dependency):

- `mini_ai/eval/__init__.py` — public API exports.
- `mini_ai/eval/tasks.py` — task registry: register tasks by name,
  load a task definition from a YAML file or a plain dict
  (`EvalTask`, `TASK_REGISTRY`, `load_task`, `load_builtin_tasks`).
  A task has a name, description, `prompt_template`
  (`str.format`, e.g. `"Question: {question}\nAnswer:"`), inline
  `items` (each with an `answer` reference plus the template's
  fields), metric names, and filter specs. The `answer` field is
  never passed to the template, so a prompt cannot leak its
  reference. Unknown metric/filter names fail at load time, not
  mid-run.
- `mini_ai/eval/tasks/qa_toy.yaml` — the shipped example task: 4
  hand-written Q&A items (capital of France, 2 + 3, water's symbol,
  largest planet), answers stored canonical (stripped, lowercase),
  metrics `[exact_match, accuracy]`, filters `[strip, lowercase]`.
- `mini_ai/eval/metrics.py` — metric registry (`METRIC_REGISTRY`,
  `register_metric`): `exact_match` (pairwise, strict equality —
  normalisation is the filters' job), `accuracy` (aggregate: mean
  of the per-item exact-match scores), `perplexity` (logprob:
  `exp(-mean log-probs)` or `exp(mean token losses)`; exactly one
  convention must be supplied, and a log-prob above 0 or a loss
  below 0 is rejected). Hand-check: log-probs
  `[ln(0.5), ln(0.25)]` give `sqrt(8) ≈ 2.828427`.
- `mini_ai/eval/filters.py` — filter registry (`FILTER_REGISTRY`,
  `register_filter`) and pipeline (`apply_filters`, applied in
  order, so order is part of a task's definition): `strip`,
  `lowercase`, `take_first_line`, `collapse_whitespace`,
  `extract_after_marker` (marker argument, case-sensitive, returns
  the text unchanged when the marker is absent). A filter spec is a
  plain name or a `{"name": ..., <arg>: ...}` dict.
- `mini_ai/eval/runner.py` — `run_task(task, scorer)` runs a task
  end-to-end: the scorer maps prompt -> output text, or
  `{"text": ..., "log_probs": [...]}` when it can supply log-probs.
  Returns a plain JSON-able results dict (per-item prompts, raw and
  filtered predictions, references, exact-match flags; aggregate
  metric values; `needs_human_decision: true`,
  `verified: false`). Perplexity is the mean of the per-item
  perplexities over items that supplied log-probs, and `None` with
  a note when none did — a missing measurement is reported as
  missing, never invented.
- `mini_ai/eval/yaml_subset.py` — a tiny original YAML-subset
  parser, so task files need no new dependency: PyYAML (6.0.1) is
  present in the dev environment but is NOT declared in
  `requirements.txt`, and adding a dependency for a handful of small
  task files would be the wrong trade. Supported: `#` comments,
  mappings by indentation (spaces only), block sequences of scalars
  or mappings, inline flow lists, null/bool/int/float/plain/quoted
  scalars. NOT supported (raises `YamlSubsetError` with a line
  number): block scalars, anchors/aliases/tags, inline flow
  mappings, tabs. If a task file ever needs full YAML, that is a
  deliberate decision to add PyYAML to `requirements.txt`.

Use it:

```python
from mini_ai.eval import load_builtin_tasks, run_task_by_name

load_builtin_tasks()
results = run_task_by_name("qa_toy", lambda prompt: "paris")
print(results["metrics"])  # {"exact_match": ..., "accuracy": ...}
print(results["needs_human_decision"], results["verified"])  # True False
```

Tests: `tests/test_eval_registry.py`, 32 tests, all passing
(2026-11-11): YAML-subset parser (7: plain mapping/scalars,
comments and quoted strings, inline list + nested mapping, list of
mappings, block-scalar rejection, duplicate-key rejection, empty
document rejection); registries (5: task/metric/filter round-trips,
unknown-task KeyError, built-ins present); filters (5: strip then
lowercase, order matters — lowercase-before-extract breaks the
case-sensitive marker while extract-before-lowercase works,
take-first-line + collapse-whitespace, unknown filter KeyError,
non-string input TypeError); metrics (5: exact-match match/no-match
including case-sensitivity, accuracy 3/4 = 0.75 on a hand-scored
set, perplexity from log-probs = sqrt(8), perplexity from token
losses = sqrt(8), perplexity rejects empty/positive-log-prob/
negative-loss/neither/both inputs); task loading (4: qa_toy YAML
loads with 4 items, built-in loader, dict validation — missing
answer / unknown metric / unknown filter — prompt never leaks the
answer); runner (6: end-to-end toy task with stub scorer —
exact_match 0.75, accuracy 0.75, 3 of 4 right; end-to-end on the
qa_toy YAML — same 0.75 scores; perplexity 2.0 from a log-prob
scorer; perplexity None with a note when the scorer supplies no
log-probs; unknown metric raises before any item is scored;
results JSON round-trip). Full ai-starter suite after this change:
92 tests OK (60 before + 32 new), 18 skipped.

Governance rule: eval scores are model results, never verified
plans. Every run result carries `needs_human_decision: true` and
`verified: false`; nothing in this package marks anything verified,
no score here bypasses the verify step, and there is no model
backend or paid API in the package at all.

Limitations / known gaps:

- The runner only knows the three built-in metric kinds
  (pairwise reported as a mean rate, aggregate applied to the
  per-item exact-match scores, logprob averaged over items with
  log-probs); a custom pairwise metric works, but there is no
  generic per-item metric column beyond exact-match.
- The YAML subset is deliberately small — no block scalars, no
  anchors, no multi-line strings — so task files must stay simple
  or move to JSON dicts.
- No scorer for a real model is included: wiring MiniGPT (or any
  model) in as a scorer is a separate step, and its log-probs would
  need to come from the model, not from this package.
- Perplexity is a mean of per-item perplexities, not a
  token-weighted aggregate across the whole task.

## mini_ai/repo_map — compact repo map (Module 20, rebuilt from Aider inspiration)

The third INSPIRATION-REBUILD item from the 70-candidate borrowing
sweep (see `start-assembly/core-spine/source-audit/
ALL_CANDIDATES_BORROWING_PLAN.md`, item 3): Aider
(Aider-AI/aider, Apache-2.0, 20,285 lines) is an AI pair-programming
CLI whose most transferable piece is its repo map
(`aider/repomap.py`, 867 lines): tree-sitter tag extraction plus
ranked, token-budgeted whole-repo context so the model sees the
codebase structure. Aider itself was NOT adopted — it needs a paid
LLM API and edits files directly, which would violate START's
trust boundaries (edits go through propose-and-approve plus the
verify step, never direct). Instead the idea was rebuilt as
original Python in `mini_ai/repo_map.py`, alongside the existing
self-edit / propose-and-approve machinery. No Aider code was read
or copied, there is no Aider dependency, and there is no paid API.
Where Aider uses tree-sitter, this module uses the stdlib `ast`
module and never imports the files it maps; where Aider ranks tags
under a token budget, this module caps file size and symbol counts
and summarises the largest files instead of dumping them.

What it does: `build_repo_map(root)` walks a repo tree and returns
a plain JSON-able dict — `schema_version` (1), `root`, `files`
(sorted by path), `counts` (by kind, plus protected / summarised /
skipped totals), `skipped_dirs`, `truncated`, `verified: false`,
`needs_human_decision: true`. Per file: relative path, kind
(`python` / `test` / `doc` / `data` / `config` / `other`), line
count, top-level symbols for Python and test files (classes with
their method names, functions, module-level assigned names and
import aliases, extracted with `ast.parse`), `editable` plus
`editable_reason`, and a `summarised` flag. Non-Python files carry
no symbols. A source file that does not parse is still listed,
with a `parse_error` note instead of symbols.

Size caps (the compactness budget): a Python file longer than
`MAX_LINES_FULL` = 500 lines is summarised — only its first
`MAX_SYMBOLS_SUMMARISED` = 20 symbols are listed; shorter files
list up to `MAX_SYMBOLS_FULL` = 100 symbols. A tree larger than
`MAX_FILES` = 2000 files is truncated (flagged, with the omitted
files counted as skipped). Skipped at every depth: `.git`,
`__pycache__`, `.venv`, `venv`, `target/`, `node_modules`,
`checkpoints`, and other build/cache dirs (the full `SKIP_DIRS`
list is recorded on every map), plus `.pyc` / checkpoint files and
symlinks, which are never followed.

Governance rule: the mapper is read-only by construction — only
`os.walk`, open-for-read, and `ast.parse`; it never writes,
renames, or deletes anything, and it never approves a diff. A repo
map is a model result, never a verified plan: every map carries
`verified: false` and `needs_human_decision: true`, following the
`mini_ai/eval` pattern. It RESPECTS THE PROTECTED-FILE LIST: the
list is read from `mini_ai.self_edit.PROTECTED` (never re-typed,
so it cannot drift from the guardrails). Every protected file
present in the tree is listed so a proposer can see it exists, but
flagged `editable: false` with reason `"protected"`, and its
symbols are NOT included — the map offers no protected content for
editing. The module must respect the protected list, never modify
it; `SAFETY.md`, `APPROVAL_POLICY.md`, `.gitignore`,
`mini_ai/self_edit.py`, and the guardrail tests were not edited.

Use it:

```python
from mini_ai.repo_map import build_repo_map, map_to_json

repo_map = build_repo_map(".")
print(repo_map["counts"])  # {"total": ..., "python": ..., ...}
print(map_to_json(repo_map)[:200])
```

Tests: `tests/test_repo_map.py`, 13 tests, all passing
(2026-11-11): kinds (9 cases) and symbol extraction (classes with
methods, functions including async, module-level names, import
aliases, parse-error note); map listing (expected files present,
`__pycache__` / `.venv` / `.git` / `target/` skipped, schema and
governance flags); Python symbols for a module and a test file;
non-Python files carry no symbols; counts (6 files: 1 python,
1 test, 2 doc, 1 data, 1 config, 1 protected); protected files
flagged `editable: false` with reason `"protected"` and symbols
withheld (including a protected Python file, `mini_ai/self_edit.py`,
and a check that its class/function names appear nowhere in the
map); read-only (contents and mtimes unchanged after two runs);
size cap (a 300-function file over 500 lines is summarised to at
most 20 symbols); JSON round-trip; empty tree. Full ai-starter
suite after this change: 105 tests OK (92 before + 13 new),
18 skipped. Checked against the real ai-starter tree as well:
423 files mapped, 9 protected files flagged, 16 files over the
500-line cap summarised.

Limitations / known gaps:

- No ranking: unlike Aider's PageRank-style tag ranking, symbols
  are listed in source order, truncated at the cap — the most
  important symbols of a very large file may sit past the cut.
- No cross-file references: the map lists per-file symbols only,
  with no call graph, import graph, or "who uses this" index.
- No incremental caching: Aider caches its map in SQLite; this
  module re-walks and re-parses the whole tree on every call.
- Line counts and symbol lists are a snapshot: a file edited after
  the map was built is stale until the map is rebuilt.

## How this fits PCAC

This repo is the language-assistance layer only, in PCAC terms:

- **People decide.** A human assembly sets goals and hard limits
  (land, water, energy, carbon) and makes the final decision.
- **A separate layer checks plans.** Allocation is checked by a
  planning / simulation calculation, not by a language model.
  PCAC v2's planning engine is that kind of layer; MiniGPT is not.
- **The language model drafts and summarises.** It can help write
  a plan draft, explain a tradeoff, or summarise a meeting. It
  must not be treated as a plan, an allocation, or a decision.
- **Narrow AI now.** No AGI is assumed. Small, local, auditable
  models first, for food, energy, housing, and care pilots.

The v1 classifier now has an `explain_ai` intent that says this
in plain language, and a `planning` response that asks for needs,
hard limits, labour and care shared fairly, a first step, and
who decides.

## Self-editing, with guardrails — not bypassed

`mini_ai/self_edit.py` lets an AI write and replace code in this
project, safely:

1. `propose_edit()` returns a diff. Nothing is written.
2. A human reads the diff and approves it.
3. `apply_edit(approved=True)` writes it, keeps a backup, runs
   tests, and rolls back automatically if tests fail.
4. `revert()` restores the backup at any time.

It cannot edit its own file, safety files, secrets, checkpoints,
or anything outside the project root, and it cannot approve its
own edit. There is no `approved=True` call left in `self_edit.py`
itself — a human approves from outside the model.

Protected, uneditable by the model, even with approval:
- `mini_ai/self_edit.py` — the approval / guardrail code itself
- `SAFETY.md` — the written safety rules
- `APPROVAL_POLICY.md` — the tiered approval policy itself
- `.gitignore` — so changes cannot be hidden from review / pushes
- `tests/test_self_edit.py`, `tests/test_tiered_approval.py`
  — so the model cannot weaken its own tests
- `self_edit_audit.jsonl` — the audit log, append-only through
  the module, never editable through a proposal

## Tiered self-approval — low and medium only

Full policy: `APPROVAL_POLICY.md`.

- **Low, self-approvable:** at most 20 changed lines, no new
  imports, no dangerous patterns, not a data file, tests pass.
- **Medium, self-approvable with second verification:** at most
  100 changed lines, standard-library imports only, no dangerous
  patterns, tests pass, and a second pass re-classifies it from
  scratch. Logged as pending human review.
- **High, human only:** larger, non-standard-library imports,
  dangerous patterns, or anything not in low/medium.
- **Never:** guardrails, safety, approval policy, audit log —
  human edits those directly, never through self-edit.

The tier is always recomputed from the diff, never claimed by
the proposer. A model cannot approve a change to its own scope.

Removing those guardrails would break PCAC corrigibility
— transparency, evaluability, and human oversight — so they are
not removable from inside a model-generated edit. A human edits
those files directly, in an editor, if the guardrails themselves
ever need to change, with a commit message saying so.

Train it on your own text by replacing `data/corpus.txt` — the
model can only learn patterns that are actually in its training
text, so a tiny corpus gives toy output, not coherent stories.
That limitation is the point: it makes the data -> model link
visible.

## Ideal-model data — science, maths, climate, modelling, engineering

New training data is kept only if it serves the intended goal:
science, mathematics, climate change, predictive modelling, and
engineering for planning within planetary limits. See
`data/IDEAL_MODEL_DATA_NOTES.md`.

- `data/science_math_climate_modelling.txt` (8,663 characters,
  63 distinct characters, original text) — science method,
  maths with worked examples, climate, and predictive modelling.
- `data/engineering.txt` (original text) — energy systems,
  materials, buildings, transport, water, and systems engineering.
- `data/weather.txt` (original text) — weather vs climate,
  variables, forecasting, extremes, and weather impacts on
  food, energy, buildings, health, and transport.
- `data/soil.txt` (original text) — soil science and nutrient
  understanding: texture, pH, NPK, cycles, balance, degradation,
  and nitrogen/phosphorus boundaries.
- `data/water_land.txt`, `data/housing.txt`,
  `data/health_care.txt`, `data/transport_logistics.txt`,
  `data/labour_care.txt` (original text) — water, land,
  housing, health, care, transport, logistics, and labour
  time, with a small selected time-series file
  `data/time_series.csv`, and a full climate series
  `data/climate_time_series_full.csv` (GISTEMP 1880-2025,
  Mauna Loa CO2 1959-2025).
- `data/local_pilot_template.md` and
  `data/local_pilot_example.csv` — consent checklist and
  SYNTHETIC teaching example only. No real community data.
- `data/corpus.txt` — PCAC planning language, kept.
- A Shakespeare drama sample was considered, then removed:
  it does not serve this goal, so it is not training data here.

## Real planning data and allocations — separate layer

`mini_ai/planning.py` is a calculation layer, not MiniGPT:

```bash
python -m mini_ai.planning
```

It uses `data/real_planning_data.csv`, an aggregated global
snapshot with sources in `data/real_planning_sources.md`:
UN population 8.2 billion in 2024; FAO food supply 2,985
kcal per capita per day in 2022, primary crops 9.9 billion
tonnes and cereals 3.1 billion tonnes in 2023 (FAOSTAT,
CC-BY-4.0); renewables just over 30% of world electricity in
2023 (OWID/Ember) and 14.6% of primary energy (Energy
Institute); 510 GW renewable capacity added in 2023 (IEA);
steel 1,892 million tonnes in 2023. It computes a global food
energy balance, an electricity allocation by CO2 intensity,
and a steel/cement scale summary — with warnings that a
global average does not allocate to a real community and
does not decide anything. People decide; this checks.

## How to grow it — in order

1. **Add intents:** add examples in `mini_ai/data.py`, retrain. This is
   the fastest way to make it yours.
2. **Understand the maths:** read the back-prop code in `neural_net.py`
   line by line, then look at the GitHub references below.
3. **Make it generate text, not just classify:** done — see MiniGPT
   above. Next is better data and tokenization, not just more layers.
4. **Make it useful locally:** plug a small open model in via Ollama or
   llama.cpp for real language, and keep this classifier as the
   small, auditable router in front of it. That matches the
   cooperative / local-first idea: small auditable models first,
   big models only where needed.

## GitHub references found useful (study, don't just copy)

- **Karpathy — micrograd / nanoGPT lineage:** the canonical
  from-scratch path. Start with autograd, then a tiny MLP, then a
  transformer. Notes repo:
  https://github.com/chizkidd/Karpathy-Neural-Networks-Zero-to-Hero
- **karpathy-microgpt** — a GPT in 243 lines of pure Python, no
  PyTorch, no NumPy, hand-rolled autograd, attention and Adam:
  https://github.com/kibotu/karpathy-microgpt
  Good next step after this starter if you want text generation
  from scratch.
- **LiteGPT** — a 124M small language model, pre-trained and
  fine-tuned, in the nanoGPT style:
  https://github.com/kmkrofficial/LiteGPT
  Good example of what "small but real" looks like after the toy stage.
- **Local AI assistants via Ollama:** for running a small model
  fully locally instead of training one:
  https://github.com/ritiksharma33/local-ai-assistant
  and for private retrieval (RAG) with local models:
  https://github.com/jonfairbanks/local-rag

Check each repo's licence before reusing its code. The code in
this folder is original and intentionally tiny.
