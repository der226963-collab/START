# Training data notes

## What this corpus is
`corpus.txt` is original text written for this project. It is not
scraped, it contains no personal data, and it is not a copy of
PCAC documents. Its themes are deliberately PCAC-aligned:

- Meet needs for everyone: food, energy, housing, care.
- Hard limits first: land, water, energy, carbon.
- Share labour and care fairly, and let necessary work time fall
  as machines do more.
- Start small and pilot: one street, one food hub, one energy
  cooperative, then scale what works.
- Keep layers separate: people in assembly decide; a separate
  calculation checks whether a plan fits the limits; a language
  model only drafts and summarises.

## What it is not
It is not a planning dataset. It contains no real allocations,
no real community data, and no real measurements. A model trained
on it learns sentence patterns about planning, not how to plan.
Do not use it, or a model trained on it, to allocate real food,
energy, housing, or care.

## Provenance
`train_gpt.py` records the corpus file name and SHA-256 in the
checkpoint JSON, so a checkpoint can be traced back to the exact
text it was trained on. If you change the corpus, retrain — do not
reuse an old checkpoint and claim it was trained on the new text.

## Next data steps, in order
1. More original text in the same style, with more varied
   sentences, before any larger model.
2. A real, licensed, public-domain dataset for language modelling
   (for example Tiny Shakespeare, the classic nanoGPT starter),
   kept separate from PCAC planning data.
3. Real planning data only under PCAC rules: consented, aggregated,
   public or licensed, with source, date, and quality recorded —
   never a language-model corpus dressed up as a plan.
