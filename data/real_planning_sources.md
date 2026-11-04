# Real planning data — sources, licences, and limits

This is a **snapshot**, not a full dataset download. Every value in
`real_planning_data.csv` is an aggregated global figure, with its
year, unit, and source in the same row. No personal data, no
individual or community data, and no scraped private data is in it.

## Primary sources, in order of strength

- **FAO FAOSTAT, CC-BY-4.0** — primary crops, cereals, sugar,
  vegetables, oil crops, fruit, roots and tubers, 2023, from
  FAOSTAT Analytical Brief 96, Agricultural production statistics
  2010-2023. Food supply in kcal per capita per day from FAO
  Food Balance Sheets 2010-2022 (2,985 in 2022) and 2010-2023
  (crossed 3,000 in 2023). These are the strongest figures here.
- **UN World Population Prospects 2024** — 8.2 billion people in
  2024, peak about 10.3 billion in the mid-2080s. A projection,
  not a measurement of the future.
- **Our World in Data, CC BY** — CO2 dataset (Global Carbon
  Project) and energy data (Energy Institute, Ember). Renewables
  just over 30% of world electricity in 2023; CO2 per capita
  about 4.7 tonnes in 2023, just below 5 tonnes for over a decade.
  OWID's own licence is CC BY; third-party data inside OWID
  follows its original terms, credited here.
- **IEA Renewables 2023** — 510 GW renewable capacity added in
  2023, solar about three quarters of additions, forecast to
  7,300 GW by 2028 under existing policies. A report, not a
  dataset download.
- **NASA GISTEMP, US government public data** — 2024 warmest
  year on record: 1.28 degrees Celsius above 1951-1980, about
  1.47 degrees above 1850-1900, after 15 consecutive months of
  monthly records June 2023-August 2024.
- **WMO / IPCC** — climate is weather over 30 years (normals
  e.g. 1991-2020); air holds about 7 percent more moisture per
  1 degree Celsius warming, making heavy rainfall more intense
  in many places. These are rules and records, not a local
  forecast.
- **FAO soil** — 95 percent of world food is grown in soil;
  about 33 percent of global soils are moderately to highly
  degraded, with a warning they could rise to 90 percent by
  2050 if trends continue.
- **Planetary Health Check 2025 (PIK)** — phosphorus
  application to cropland about 18.2 Tg P per year, about 3
  times the regional boundary of 6.2 Tg P per year; nitrogen
  fixation about 165 Tg N per year, more than twice its
  boundary, high-risk zone. These are global boundaries, not
  a field-level fertiliser recommendation.
- **Energy Institute Statistical Review of World Energy 2024**
  (as reported) — renewables 14.6% of primary energy in 2023.
  Note: electricity share (30%) and primary energy share
  (14.6%) are different denominators. Do not mix them.

## Secondary / order-of-magnitude figures — use with care

- Steel 1,892 million tonnes in 2023, about 2.8 billion tonnes
  CO2, about 8% of global GHG, from a UN SDSN Iron and Steel
  brief citing IEA. Cement about 2.3 billion tonnes CO2 per year,
  530 kg cement and 240 kg steel per person per year, from IEA
  figures as summarised in Nature. These are useful for scale,
  not for plant-level planning. If a real local plan needs steel
  or cement, get the plant, region, and year data directly.

## What this snapshot does NOT do

- It does **not** allocate food, energy, or materials to a real
  community. Global averages hide distribution: a global food
  surplus in kcal does not mean every person is fed.
- It does **not** replace a full FAOSTAT, OWID, or IEA download.
  For serious planning, download the full dataset, check its
  version, and record its hash and date.
- It does **not** make MiniGPT a planner. The calculation in
  `mini_ai/planning.py` is a separate layer, with its own
  assumptions stated in code and in its output.
- Values are rounded in the CSV where the source itself rounds.
  Do not present a rounded snapshot as exact to the last digit.

## How to update it

Replace a row only with a newer value from the same source, keep
the old year in a new row, and update this file with the new
source date. Do not silently overwrite a year.
