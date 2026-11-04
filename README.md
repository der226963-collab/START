# AI Starter — a small, local, auditable beginning

This is a separate side project from the PCAC blueprint. It is not a
frontier chatbot, and it does not call an external AI API.

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
python -m pytest tests/ -q
# or, without pytest:
python tests/test_neural_net.py
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
