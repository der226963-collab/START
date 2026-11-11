# ISSUE-17 — v0.3.1 compatibility mapping (recorded BEFORE port code, 2026-11-11)

Source (read-only, never modified): `~/workspace/ai-starter/tests/test_planning.py`
(9 functions) and `~/workspace/ai-starter/mini_ai/planning.py`.
v0.3.1 suite reproduced live from that tree before porting: **9/9 pass**
(run from `~/workspace/ai-starter` with the core-spine venv pytest).
Review-copy Python baseline at mapping time: **296/296**.

Verdicts: **already-equivalent** = a v0.3.2 path reproduces the tested
numbers as-is (evidence cited); **portable** = no v0.3.2 equivalent, the
calculation is restored verbatim in `domains/compat_v031.py`; **not
portable** = cannot be ported, with the reason. Nothing is silently
skipped: all 9 functions are accounted for below, and the backtest
(test 8) is test-pinned behaviour, so it is ported, not skipped.

| # | v0.3.1 test function | Verdict | Evidence / port |
|---|---|---|---|
| 1 | `test_snapshot_loads_and_has_key_rows` | already-equivalent | ISSUE-01: `contracts/plan_limits.load_snapshot()` loads the byte-identical `data/real_planning_data.csv` (58 rows); `tests/test_issue01_plan_limits.py` already asserts the key indicators/values. Compat suite re-asserts the three indicators from the test. |
| 2 | `test_food_balance_supply_above_planning_need_on_average` | already-equivalent (at the tested point) | Food 2985/need 2500/losses 0/imports 0 → surplus 485.0 in BOTH formulas (ISSUE-15, verified live). Reproduced via the v0.3.2 engine path (`FoodDomain` + `PlanningEngine`) in the compat suite. The formulas DIVERGE off that point (2800/2500: v0.3.1 300 vs v0.3.2 176.0 at imports 100/losses 0.08) — the compat suite asserts the documented v0.3.2 behaviour with that note, never the old number as current. |
| 3 | `test_electricity_allocation_low_carbon_beats_current` | portable | No v0.3.2 equivalent (only the CO2-intensity constants were ported in ISSUE-01). Calculation ported verbatim to `domains/compat_v031.py:electricity_allocation()`; exact totals verified live from v0.3.1: current 12,485.7 Mt, low-carbon 5,280.0 Mt. |
| 4 | `test_run_plan_is_calculation_not_language` | portable | No v0.3.2 equivalent. `run_plan()` ported verbatim (assembles food/weather/soil/systems/climate/pilot/energy/backtest/plan-check); cereals 3100, `layer` startswith "calculation". |
| 5 | `test_soil_summary_phosphorus_excess` | portable | No v0.3.2 equivalent. Ported verbatim: degraded 33%, P excess 12.0 Tg/yr, teaching N balance 20. |
| 6 | `test_systems_summary_ratios` | portable | No v0.3.2 equivalent. Ported verbatim: ag land 0.585, cropland 0.195 ha/person, road CO2 6180.0 Mt, unpaid care 16.4 bn h/day. |
| 7 | `test_climate_trend_and_pilot_example` | portable — data port required | No v0.3.2 equivalent. Needs the full climate series (146 yrs, CO2 315.98→427.35) and the synthetic pilot file — both deliberately NOT ported in ISSUE-01, both ported here (byte-identical, provenance in `data/SNAPSHOT_PROVENANCE.md`). The already-ported `data/time_series.csv` does NOT suffice: 15 selected years only, no 1880–1899/1959 rows, no per-year series for means/backtest. Pilot: 20 people, status startswith SYNTHETIC; the ISSUE-36 raise-guard is RE-ASSESSED and ENFORCED now that the file exists (see below). |
| 8 | `test_backtest_and_plan_limits` | portable (backtest) + already-equivalent with a DOCUMENTED breaking difference (plan limits) | Backtest is test-pinned behaviour: ported verbatim (linear trend, train ≤1999, test 2000–2025; temp bias −0.453, CO2 bias −13.079, both < 0). Plan limits: already ported in ISSUE-01 (`contracts/plan_limits.check_plan_limits`): P 5.0/work 40 passes, P 18.2/work 55 fails with count 2, nitrogen-only check status UNKNOWN — all reproduced. DELIBERATE DIFFERENCE (ISSUE-02, `docs/BREAKING_CHANGES.md`): v0.3.1's nitrogen-only plan returned `passes_checked_limits: True`; v0.3.2 returns `overall_status: UNKNOWN` (UNKNOWN blocks a pass) and an empty plan returns `NOT_CHECKED`, not a pass. The compat suite asserts the v0.3.2 behaviour and notes the difference; it does NOT assert the old aggregate as current. |
| 9 | `test_weather_summary_uses_real_anomaly_and_moisture_rule` | portable | No v0.3.2 equivalent. Ported verbatim: anomaly 1.28 °C, moisture 7.0% per 1 °C warming. |

## Nothing not portable

No v0.3.1 tested behaviour was found unportable. Every one of the 9
functions maps to an already-equivalent path or a ported calculation.
No behaviour depended on a capability the review copy was never meant
to have (no neural-network, MiniGPT, agent, or live-data behaviour is
tested by `test_planning.py`; `energy_and_materials()` is not itself a
test function but is part of `run_plan()` and is ported with it).

## Data decisions (recorded explicitly)

- **Full climate series PORTED**: `data/climate_time_series_full.csv`,
  byte-identical copy of `~/workspace/ai-starter/data/climate_time_series_full.csv`
  (md5 `2ce1989356dd89b14e74ec990a5abd52`, 146 data rows + header).
  Required: `climate_trend()` needs the 1880–1899 and 2000–2025 means
  and CO2 1959; `backtest_climate()` needs per-year values 1880–2025.
  `data/time_series.csv` (15 selected years) cannot supply either.
- **Synthetic pilot file PORTED**: `data/local_pilot_example.csv`,
  byte-identical copy of `~/workspace/ai-starter/data/local_pilot_example.csv`
  (md5 `9e26fc98c09ae1c3d4e2c95d9bd6fdc3`, 5 data rows + header).
  Required for the pilot half of test 7 (20 people, SYNTHETIC).
- **ISSUE-36 guard re-assessed**: the raise-guard in v0.3.1
  `pilot_summary()` (raise `ValueError` if any `household_id` lacks
  `SYNTH`) was documented as intentionally deferred *because the pilot
  file was absent*. The file now exists in-tree, so the deferral's
  premise no longer holds: the guard is ENFORCED in the ported
  `pilot_summary()` (non-SYNTH row raises), and the result carries
  `data_status: "synthetic"` (the `DataStatus.SYNTHETIC` labelling
  already enforced by `domains/food/production.py:data_status_for`)
  plus the SYNTHETIC warning. The `docs/ARCHITECTURE.md` ISSUE-36
  section is updated to record this.
- Nothing else from v0.3.1 data was ported; no values were edited,
  rounded, or invented. Provenance entries added to
  `data/SNAPSHOT_PROVENANCE.md`.

## Deliberate differences (v0.3.2 behaviour asserted, old behaviour noted)

1. **Aggregation (ISSUE-02)**: empty plan → `NOT_CHECKED`;
   nitrogen-only plan → single check `UNKNOWN`, `overall_status`
   `UNKNOWN` (v0.3.1: `passes_checked_limits: True`). Safer rule kept.
2. **Food formula (ISSUE-15)**: v0.3.2 surplus includes losses/imports;
   agrees with v0.3.1 only at losses 0/imports 0. The compat
   `food_balance()` in `domains/compat_v031.py` is the v0.3.1 formula
   kept ONLY as a labelled compatibility reference (its docstring says
   so); the engine path is authoritative for new work.
3. **Status vocabulary**: v0.3.1 lowercase `"unknown"`/`"pass"`/`"fail"`;
   v0.3.2 uppercase enum (`UNKNOWN`/`PASS`/`FAIL`). Compat tests assert
   the v0.3.2 strings; the mapping to the old strings is noted in the
   test comments.
4. **Validation strictness**: v0.3.1 silently accepted e.g. `True` for
   work hours; v0.3.2 rejects non-numeric/bool inputs. Not re-tested
   as compat behaviour (the stricter rule is the documented improvement).
