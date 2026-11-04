# Ideal-model data — what is kept, what is removed, and why

## Selection rule

New training data for this project is kept only if it serves the
ideal model: science, mathematics, understanding of climate
change, and predictive modelling, in PCAC terms — meeting needs
for everyone within land, water, energy, and carbon limits,
with human assemblies deciding.

Data that does not serve that purpose is not kept as training
data, even if it is public domain, famous, or useful for a
general language model.

## Removed — 2026-11-04

- `data/tinyshakespeare_sample.txt` — REMOVED from the training
  set. It was a 2,315-character sample of Tiny Shakespeare drama.
  It is public domain, but it teaches dialogue patterns, not
  science, mathematics, climate, or modelling.
- `data/NEW_DATA_NOTES.md` — removed with it, as it described
  that sample.
- Both files were moved to recoverable trash (30 days), not
  permanently deleted, so they can be restored if that decision
  is reversed. They were never pushed to GitHub, so the repo
  was never changed by them.

## Kept — ideal-model data

0. `data/real_planning_data.csv` + `data/real_planning_sources.md`
   - Aggregated global real data, not training text for MiniGPT.
   - Used by the separate calculation layer `mini_ai/planning.py`
     for food, energy, and materials allocations. See that file
     and the sources file for licences and limits.

1. `data/engineering.txt` (original text)
   - Energy, materials, buildings, transport, water, and systems
     engineering, with real 2023 anchors: renewables over 30%
     of electricity, 510 GW added, steel 1,892 million tonnes.

2. `data/soil.txt` (original text)
   - Soil science, texture, structure, pH, NPK and
     micronutrients, nutrient cycles, balance, degradation,
     and planetary boundaries for nitrogen and phosphorus.

3. `data/weather.txt` (original text)
   - Weather vs climate, variables, instruments, forecasting,
     extremes, and how weather affects food, energy, buildings,
     health, and transport.

3. `data/corpus.txt` (3,302 characters, PCAC-aligned)
   - Planning language: needs, limits, labour and care shared
     fairly, assemblies deciding. Kept, because it is the
     language the ideal model must speak.

2. `data/science_math_climate_modelling.txt` (new, original text)
   - Science: observation, hypothesis, evidence, measurement,
     uncertainty, peer review.
   - Mathematics: arithmetic, variables, equations, functions,
     averages, probability, optimisation under constraints,
     with worked examples.
   - Climate change: greenhouse effect, carbon budget, sea
     level, mitigation, adaptation, planetary boundaries,
     climate justice.
   - Predictive modelling: models as simplified representations,
     inputs, parameters, validation, scenarios, uncertainty
     ranges, and the limit that models do not decide.

This file is original text written for this project. It is not
a copy of a textbook, paper, or dataset, and it contains no
personal data and no real allocations for a real community.

## Layer rule — read this before using the data

- A language model trained on this text learns *language* in
  these domains. It does not learn to calculate, allocate, or
  decide.
- Predictive modelling itself is a separate calculation layer:
  a mathematical planning / simulation model that checks
  allocations under hard limits. That layer is not MiniGPT.
- Keep the layers separate: people set goals and limits,
  calculation checks a plan, language explains a plan,
  assemblies decide.

## What would qualify next

Only data that fits the four areas above, with source, licence,
and permission recorded, and with no personal or non-consensual
data. Examples, in priority order, for future work (not yet added):

- Original explanatory text on energy systems, food systems,
  housing, and care, with numbers and limits.
- Public-domain US government climate explanations (NASA / NOAA),
  checked and cited, not scraped at scale.
- A small, clearly labelled numerical dataset for a forecasting
  exercise (for the calculation layer, not for MiniGPT text
  training), with its source and units stated.

## Train command

For the new ideal-model text file:

```
python train_gpt.py --data data/science_math_climate_modelling.txt --size tiny --steps 500
```

For the PCAC planning corpus, separately:

```
python train_gpt.py --data data/corpus.txt --size tiny --steps 500
```

Do not mix in drama, stories, or general web text and still call
the result an ideal-model dataset.
