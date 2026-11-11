# Snapshot provenance — v0.3.1 real-world data ported into the v0.3.2 review copy

Ported 2026-11-11 (ISSUE-01 fix). Review copy only, local, never pushed.
Source tree (read-only, never modified): `~/workspace/ai-starter/`
(v0.3.1, der226963-collab/START).

## Files ported

| File in this folder | Source file | md5 | Rows |
|---|---|---|---|
| `real_planning_data.csv` | `data/real_planning_data.csv` | `e4494dd3e201d73f4f5927784d3928bf` | 58 data rows + header (59 lines) |
| `real_planning_sources.md` | `data/real_planning_sources.md` | `3fa508a528ec887136d04a73c9be4eba` | 129 lines |
| `time_series.csv` | `data/time_series.csv` | `aa643e69c1fe8aee0f1da5bd3728d443` | 15 data rows + header (16 lines) |
| `climate_time_series_full.csv` | `data/climate_time_series_full.csv` | `2ce1989356dd89b14e74ec990a5abd52` | 146 data rows + header (147 lines) |
| `local_pilot_example.csv` | `data/local_pilot_example.csv` | `9e26fc98c09ae1c3d4e2c95d9bd6fdc3` | 5 data rows + header (6 lines) |

All three files are byte-identical copies of the v0.3.1 sources. No value
was edited, rounded, or invented. Per-row source and licence/status are in
the CSVs themselves (`source`, `licence_or_status`, `note` columns) and in
`real_planning_sources.md`. Snapshot version recorded in code as
`SNAPSHOT_VERSION = "v0.3.1-2026-11-04"` (the v0.3.1 snapshot as it stood
when the review was written); constraint-set version `1.0.0`
(see `contracts/plan_limits.py`).

## Key values from the ISSUE-01 grep list — where each one lives

| Value | Where it lives in the ported data | What it is |
|---|---|---|
| 2985 | `real_planning_data.csv`: `global_food_supply_dietary_energy`, 2022, kcal per capita per day | FAO Food Balance Sheets 2010–2022, CC-BY-4.0 via FAOSTAT. Supply, not intake; average hides distribution. |
| 6.2 | `real_planning_data.csv`: `phosphorus_regional_boundary`, 2025, Tg P per year | Planetary Health Check 2025 (PIK report). Regional boundary for phosphorus application to cropland. |
| 18.2 | `real_planning_data.csv`: `phosphorus_application_to_cropland`, 2025, Tg P per year | Planetary Health Check 2025. About 3× the 6.2 boundary. |
| 165 | `real_planning_data.csv`: `nitrogen_fixation`, 2025, Tg N per year | Planetary Health Check 2025. "More than twice its boundary; high-risk zone". No exact N boundary is stored anywhere in the snapshot. |
| 48 | **Not a CSV row.** Hard-coded boundary in v0.3.1 `mini_ai/planning.py:check_plan_limits()` | ILO long-hours threshold, hours per week. Ported as the stored bound of the `paid_work_hours_per_week` constraint in `contracts/plan_limits.py`, with the same "not a PCAC rule" note. |
| 820 | **Not a CSV row.** Constant in v0.3.1 `mini_ai/planning.py:CO2_INTENSITY_G_PER_KWH` | Lifecycle CO2 intensity for coal, g CO2/kWh. IPCC median-style illustrative value, stated in the code so it can be challenged; NOT in the snapshot CSV and NOT real-time grid data. Ported as `CO2_INTENSITY_G_PER_KWH` in `contracts/plan_limits.py` with that warning preserved. |
| 1.28 | `real_planning_data.csv`: `global_temperature_anomaly_vs_1951_1980`, 2024, °C | NASA GISTEMP, US government public data. Warmest year on record in NASA analysis. |
| 427.35 | **Not in the snapshot CSV.** `time_series.csv`: `mauna_loa_co2_annual_mean`, 2025, ppm (also `climate_time_series_full.csv` in v0.3.1, not ported) | NOAA GML via secondary compilation. Annual mean as reported in 2026 compilations. Ported here via `time_series.csv` so the value is present and sourced; the full climate series was out of scope for this port. |

## Ambiguities and things deliberately NOT ported as facts

- **2500 kcal/capita/day (food planning need) is an assumption, not a
  FAO figure.** v0.3.1 `planning.py:food_balance()` states this explicitly:
  "2500 is a round planning figure, above the WFP-style 2100 minimum and
  below the 2022 global supply average." It is stored as the default food
  bound in the versioned constraint set, labelled as an assumption.
- **Nitrogen has no boundary.** The snapshot records only that 165 Tg N/yr
  is "more than twice its boundary". No exact N boundary value exists in
  v0.3.1, so none is invented: the nitrogen constraint is stored
  bound-less and always evaluates UNKNOWN, never PASS.
- **2023 food supply 3000** is in the CSV as a "historic milestone crossed
  in 2023; value is milestone not exact to 1 kcal". The 485 surplus
  reproduction uses the 2022 figure (2985), matching v0.3.1.
- **2026-dated rows** (`paid_work_hours_per_week_*`, 2026;
  `people_lacking_adequate_housing`, 2026) are ported exactly as stored;
  their years are the source's, not this port's.
- **The full climate time series** (`climate_time_series_full.csv`,
  GISTEMP/NOAA 1880–2025) and the synthetic pilot file
  (`local_pilot_example.csv`) were NOT ported in ISSUE-01. Both were
  ported 2026-11-11 as part of ISSUE-17 (see the two rows added to the
  table above): the full series is required for `climate_trend()` /
  `backtest_climate()` in `domains/compat_v031.py` — the 15 selected
  years in `time_series.csv` cannot supply the 1880–1899 / 2000–2025
  means, CO2 1959, or per-year backtest values — and the pilot file is
  required for the pilot half of v0.3.1 test 7. The pilot file is
  SYNTHETIC teaching/test data, not real-world data; the v0.3.1
  raise-guard on non-SYNTH rows is enforced by the ported
  `pilot_summary()` (ISSUE-36 re-assessment, see
  `docs/COMPAT_V031_MAPPING.md`).
- **Global averages hide distribution.** Preserved from v0.3.1: a surplus
  on average does not mean every person is fed; real allocation must be
  per region and per household. Nothing in this port allocates or decides
  anything.

## How the snapshot is used

`contracts/plan_limits.py` loads `real_planning_data.csv` (never edited by
code), builds the versioned constraint set from it, and is the only place
the snapshot's limit values enter the engine. `PlanningEngine` loads that
constraint set by default; `examples/global_food_balance.py` reproduces
the v0.3.1 485 kcal/capita/day surplus from the loaded snapshot.
