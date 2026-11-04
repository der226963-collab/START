# Local pilot data template — read this first

This template is for a REAL local pilot only when a real community
has consented. It does not contain real community data.

## What is not in this repo

No real household, person, address, farm, or community is named
in this template. The example file `local_pilot_example.csv` is
SYNTHETIC teaching data for a fictional place called
Exampleville. It is not a real community, not real people, and
must not be used for a real allocation, a real decision, or a
real report about any real place.

## Consent checklist — all must be true before real data is added

1. A community assembly, or the community's own decision body,
   has agreed to take part, in its own words, on its own terms.
2. Each household or person in the data has given informed
   consent, knowing what will be collected, who will see it,
   how long it will be kept, and that they can withdraw.
3. Data that could identify a person is kept out of the public
   repo. Only aggregated, anonymised summaries go public, and
   only if the community agrees.
4. The community can see, correct, and delete its data.
5. The community decides how the plan is used. A model checks
   a plan; it does not decide for the community.
6. No data is collected from children, patients, or other
   vulnerable people without their own consent process and
   the community's safeguards.
7. If consent is withdrawn, the data is removed, and any
   public summary based on it is corrected or removed.

If any item is not true, do not add real data. Use the
synthetic example only, for teaching and testing code.

## Fields to collect, if consented

- household_id: an anonymous code, not a name or address
- people_in_household: number
- land_hectares_available: hectares the household can use
- soil_tested: yes or no, and date of last test if yes
- water_source: rain, well, river, piped, other — no location
- food_kcal_needed_per_day: people x planning need, with
  need stated openly, not hidden
- food_kcal_produced_per_year: from farm records, if kept
- energy_kwh_needed_per_year: household estimate
- housing_adequate: yes or no, by the seven UN dimensions
- care_hours_per_week: unpaid care hours, shared fairly
- transport_km_per_week: distance to work, school, care
- notes: only what the household agrees to share

## How to use the synthetic example

`local_pilot_example.csv` shows the shape of the data and
lets the planning code be tested. Totals from it are
teaching totals, not real needs. A real pilot must replace
it, field by field, only after the consent checklist above
is met, and must not keep the synthetic rows mixed with
real rows.
