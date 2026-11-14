# Ready-made CLI example inputs

Every file here is a persistence envelope (`schema_version`, `kind`,
`saved_at`, `payload`) that the CLI accepts as-is. Run them from the
tree root, e.g.:

    python -m cli check-plan --plan examples/cli-inputs/plan-pass.json --out /tmp/result.json

No file here invents data. Snapshot values were taken from the
versioned snapshot (`data/real_planning_data.csv`,
v0.3.1-2026-11-04) through `contracts.plan_limits`; example requests
come from the tree's own example scripts and tests, as noted per
file. `tests/test_issue27_cli_examples.py` runs every file through
the real CLI and asserts the expected outcome, so these inputs cannot
go stale silently.

## Plan checks (`check-plan`)

- `plan-pass.json` — the v0.3.1 example plan from
  `tests/test_issue01_plan_limits.py`: phosphorus 5.0 Tg/yr, food
  2600 vs a 2500 need, paid work 40 h/week.
  Expected: overall **PASS**, failed 0.
  `python -m cli check-plan --plan examples/cli-inputs/plan-pass.json --out /tmp/result.json`
- `plan-fail.json` — the same plan with phosphorus 18.2 Tg/yr and
  paid work 55 h/week (the ISSUE-01 failing case).
  Expected: overall **FAIL**, failed 2 (phosphorus, paid work).
  `python -m cli check-plan --plan examples/cli-inputs/plan-fail.json --out /tmp/result.json`
- `plan-overrides-match.json` — a `plan_overrides` envelope stating
  the phosphorus boundary as 6.2 Tg/yr, exactly the stored bound, so
  it is accepted as a no-op confirmation (see
  `contracts/plan_limits.py`: an override that differs from the
  stored bound is refused).
  Expected with the passing plan: overall **PASS**.
  `python -m cli check-plan --plan examples/cli-inputs/plan-pass.json --overrides examples/cli-inputs/plan-overrides-match.json --out /tmp/result.json`

## Domain runs (`run`)

- `food-request.json` — the community request from
  `examples/food_balance.py` (population 100,000; supply 2800,
  requirement 2500, imports 100 kcal/capita/day; losses 8%).
  Expected: calculation **COMPLETED**, overall **PASS**.
  `python -m cli run --domain food --request examples/cli-inputs/food-request.json --out /tmp/result.json`
- `labour-request.json` — the global snapshot values from
  `examples/global_labour_balance.py`: unpaid care 16.4 billion
  hours/day (ILO 2018), women's share 76.2%, paid work 43 h/week
  (employed average, 2026), population 8.2 billion (2024).
  Expected: calculation **COMPLETED**; women 12.4968 / men 3.9032
  billion hours/day; care per person 2.0 hours/person/day (the 2018
  care / 2024 population year mismatch is stated as a limitation in
  the result, as in the example script).
  `python -m cli run --domain labour --request examples/cli-inputs/labour-request.json --out /tmp/result.json`
- `nutrients-request.json` — snapshot values only: phosphorus
  applied 18.2 Tg/yr, nitrogen fixation 165 Tg/yr (2025). The
  snapshot carries NO uptake or loss figures, and none are stated
  here — so the balance honestly reports **INSUFFICIENT_INPUT** and
  names the four missing inputs, exactly as
  `examples/global_nutrient_balance.py` does. The boundary checks
  still run through `check-plan` (see `plan-fail.json` above).
  `python -m cli run --domain nutrients --request examples/cli-inputs/nutrients-request.json --out /tmp/result.json`
- `nutrients-teaching-request.json` — the v0.3.1 **teaching**
  example (100 applied, 50 uptake, 30 losses, 20 soil change),
  abstract units, labelled as teaching — the same labelled input
  used in `tests/test_issue34_nutrients.py`. This is the only file
  here whose numbers are not snapshot data, and it is labelled as
  such in its filename, its `source_ids`, and this README. It exists
  so the CLI can show a *completed* nutrients balance.
  Expected: calculation **COMPLETED**, nitrogen soil change 20.0.
  `python -m cli run --domain nutrients --request examples/cli-inputs/nutrients-teaching-request.json --out /tmp/result.json`

## Scenarios (`run-scenario`, `compare-scenarios`)

Both scenarios share the food base request from `food-request.json`
(`metadata.base_request`) and change one allowed field each
(food scenarios may change only the five availability fields):

- `food-scenario-lower-losses.json` — losses cut from 8% to 2%.
  `python -m cli run-scenario --domain food --scenario examples/cli-inputs/food-scenario-lower-losses.json --out /tmp/result.json`
- `food-scenario-higher-supply.json` — supply raised from 2800 to
  3000 kcal/capita/day.
  `python -m cli run-scenario --domain food --scenario examples/cli-inputs/food-scenario-higher-supply.json --out /tmp/result.json`
- Both together:
  `python -m cli compare-scenarios --domain food --scenarios examples/cli-inputs/food-scenario-lower-losses.json examples/cli-inputs/food-scenario-higher-supply.json --out /tmp/result.json`
  The comparison reports consequences without ranking or selecting
  (the engine never picks a scenario for you).
