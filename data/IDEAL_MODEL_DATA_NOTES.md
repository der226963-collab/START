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

- `data/water_land.txt`, `data/housing.txt`,
  `data/health_care.txt`, `data/transport_logistics.txt`,
  `data/labour_care.txt` (original text, extensive search
  2026-11-04) — water, land, housing, health, care,
  transport, logistics, labour time, with real anchors in
  the snapshot and a small selected time-series file
  `data/time_series.csv` (temperature and CO2, plus land
  years). The time-series file is a sample, not a full
  download; full GISTEMP and NOAA series should be used
  for serious predictive modelling.
- Combined-data training, 2026-11-04: `train_gpt.py
  --data-dir data --size tiny --steps 300 --dropout 0.1`
  gave 112,256 parameters, 37,626 train tokens, 4,181 val
  tokens, best val loss 2.2528, and `evaluate_gpt.py` on
  weather.txt gave loss 2.2665, perplexity 9.6. Generation
  is still toy-level. The improvement here is in code,
  evaluation, and data breadth, not in claiming coherent
  output from a tiny model on a tiny corpus.
- Modern-model training, 2026-11-04: `train_gpt.py --modern
  --data-dir data --size tiny --steps 200 --dropout 0.1`
  gave 40,275 train tokens, best val loss 1.9429, and
  evaluate on weather.txt gave loss 1.9818, perplexity 7.3,
  better than the classic model on the same short run, but
  generation is still toy-level. This is a comparison, not
  an AGI result.
- BPE + larger-model training, 2026-11-04: `train_gpt.py
  --modern --tokenizer bpe --bpe-merges 300 --data-dir data
  --size small --steps 2000 --dropout 0.1` gave a 367-token
  BPE vocabulary, 17,511 train tokens, 1,946 val tokens,
  best val loss 4.2811. By step 1200 train loss was already
  0.12 while val loss was ~6.9: the larger model memorised
  the tiny corpus instead of generalising. Evaluate on
  weather.txt gave loss 4.3414, perplexity 76.8 (per-BPE-token
  units, not directly comparable with per-character losses).
  Generation is still not fluent: real words and phrases
  appear ("planning", "emissions", "people"), but sentences
  do not hold together. Lesson recorded honestly: a bigger
  model and subword tokens alone do NOT move past toy-level
  on a ~40,000-character corpus. The binding constraint is
  data volume, not architecture. The next real step is a
  much larger corpus in the same ideal domains, or accepting
  that the language model stays a small assistant while the
  planning layer and retrieval do the real work.

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
