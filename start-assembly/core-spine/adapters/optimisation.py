"""Optimisation adapter: HiGHS (via SciPy), CPMpy, CVXPY.

Small synthetic food example, designed so all three solvers can
reproduce the SAME totals (see module docstring for the analytic
answer). It is synthetic only — not a real region, diet, or advice.

Cross-solver example (loss-free, so CPMpy's integer variables work):
  1 site, 2 crops, water is the binding constraint.
  Land 100 ha, water 100,000 m3. Labour is not binding and is omitted
  from the cross-solver LP (it is checked separately in the SciPy
  PCAC-style example below).
  Wheat:  yield 4 t/ha,  water 1,200 m3/ha, demand 250 t
  Potato: yield 20 t/ha, water 2,000 m3/ha, demand 400 t
  Variables: area per crop; production = yield * area;
  delivered = production; delivered + shortage = demand.
  Stage 1: minimise total shortage. Stage 2: minimise production
  (waste) among Stage-1 optima — same Stage-3 idea as the PCAC
  planning engine v0.1.0 (pcac-planning-engine, commit 912b3c96).

Analytic answer (water-efficient crop first):
  Potato is 0.0100 t per m3 of water, Wheat 0.00333 t per m3.
  Potato fully met: area 20.00 ha, water 40,000 m3, delivered 400 t.
  Remaining water 60,000 m3 -> Wheat area 50.00 ha, delivered 200 t.
  Totals: delivered 600 t, shortage 50 t (all Wheat), production 600 t,
  land used 70.00 ha, water used 100,000 m3 (binding).
  (An earlier draft of this file wrongly used 21.05 ha / 614 t / 57 t
  here — those are the 5%-loss figures from the PCAC-style example
  below. The test suite caught the error; the corrected totals are
  verified by all three solvers in tests/test_spine.py.)

PCAC-style example (SciPy/HiGHS only): the same site with a 5%
distribution loss and a labour check. Delivered = 0.95 * shipped.
  Potato fully met (421.05 t produced, 400 t delivered).
  Wheat: water left 57,894.74 m3 -> 192.98 t produced, 183.33 t delivered.
  Totals: delivered 583.33 t, shortage 66.67 t, production 614.04 t,
  land 69.30 ha, water 100,000 m3, labour ~2,228 h (not binding).

Solver notes (verified in this assembly, see ASSEMBLY_REPORT.md):
* HiGHS is used through SciPy `linprog` (HiGHS) — the SciPy version
  actually imported is recorded in every result (1.11.4 was the system
  version in the PCAC build); OR-Tools was NOT available in the PCAC build
  environment and is not used here either. The solver actually used
  is recorded in every result; a HiGHS result is never presented as
  an OR-Tools result.
* CPMpy is a constraint-programming modelling layer, not a solver:
  it needs a backend solver. Its default is OR-Tools (not available
  here); this adapter tries the HiGHS backend (highspy) and records
  exactly what happened if that backend is unavailable.
* CVXPY is a modelling layer, not a solver: it delegates to a
  backend (HiGHS via highspy, Clarabel, SCS, ...). The backend used
  is recorded in every result.
"""

import math

# --- shared data -------------------------------------------------------

CROPS = (
    {"name": "Wheat", "yield_t_per_ha": 4.0, "water_m3_per_ha": 1200.0,
     "labour_h_per_ha": 20.0, "demand_t": 250.0},
    {"name": "Potato", "yield_t_per_ha": 20.0, "water_m3_per_ha": 2000.0,
     "labour_h_per_ha": 60.0, "demand_t": 400.0},
)
LAND_HA = 100.0
WATER_M3 = 100_000.0
LABOUR_H = 10_000.0

EXPECTED_CROSS = {"delivered_t": 600.0, "shortage_t": 50.0,
                  "production_t": 600.0, "land_ha": 70.0,
                  "water_m3": 100_000.0}
EXPECTED_PCAC_STYLE = {"delivered_t": 583.33, "shortage_t": 66.67,
                       "production_t": 614.04, "land_ha": 69.30,
                       "water_m3": 100_000.0, "labour_h": 2228.0}


def _result(solver: str, delivered, shortage, production, land, water,
            labour=None, status="optimal"):
    return {
        "solver": solver,
        "status": status,
        "delivered_t": round(float(delivered), 2),
        "shortage_t": round(float(shortage), 2),
        "production_t": round(float(production), 2),
        "land_ha": round(float(land), 2),
        "water_m3": round(float(water), 2),
        "labour_h": (round(float(labour), 2) if labour is not None else None),
        "demand_t": 650.0,
        "example": "synthetic-1-site-2-crop",
    }


def solve_scipy_highs(loss: float = 0.0):
    """Two-stage LP via SciPy linprog (HiGHS).

    Variables: [area_w, area_p, prod_w, prod_p, deliv_w, deliv_p,
                short_w, short_p]
    Stage 1: minimise shortage. Stage 2: hold shortage at its optimum
    and minimise production (waste).
    """
    import scipy
    from scipy.optimize import linprog
    import numpy as np

    scipy_solver = f"scipy.optimize.linprog (HiGHS), scipy {scipy.__version__}"

    w, p = CROPS
    # Six separate equalities (do NOT merge them — an earlier draft
    # merged deliv=(1-loss)*prod with deliv+short=demand into one
    # row, which let the solver set production to 0 while delivered
    # stayed free; the tests caught it):
    #   prod = yield*area (2 rows)
    #   deliv = (1-loss)*prod (2 rows)
    #   deliv + short = demand (2 rows)
    A_eq = np.zeros((6, 8))
    b_eq = np.array([0.0, 0.0, 0.0, 0.0, w["demand_t"], p["demand_t"]])
    A_eq[0, 0], A_eq[0, 2] = -w["yield_t_per_ha"], 1.0
    A_eq[1, 1], A_eq[1, 3] = -p["yield_t_per_ha"], 1.0
    A_eq[2, 2], A_eq[2, 4] = -(1.0 - loss), 1.0
    A_eq[3, 3], A_eq[3, 5] = -(1.0 - loss), 1.0
    A_eq[4, 4], A_eq[4, 6] = 1.0, 1.0
    A_eq[5, 5], A_eq[5, 7] = 1.0, 1.0
    # inequalities: land, water
    A_ub = np.array([
        [1.0, 1.0, 0, 0, 0, 0, 0, 0],
        [w["water_m3_per_ha"], p["water_m3_per_ha"], 0, 0, 0, 0, 0, 0],
    ])
    b_ub = np.array([LAND_HA, WATER_M3])
    bounds = [(0, None)] * 8

    r1 = linprog(c=[0, 0, 0, 0, 0, 0, 1, 1], A_ub=A_ub, b_ub=b_ub,
                 A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs")
    if not r1.success:
        return {"solver": scipy_solver,
                "status": f"failed: {r1.message}"}
    shortage_opt = float(r1.fun)
    # Stage 2: shortage fixed at optimum, minimise production.
    A_eq2 = np.vstack([A_eq, [0, 0, 0, 0, 0, 0, 1, 1]])
    b_eq2 = np.append(b_eq, shortage_opt)
    r2 = linprog(c=[0, 0, 1, 1, 0, 0, 0, 0], A_ub=A_ub, b_ub=b_ub,
                 A_eq=A_eq2, b_eq=b_eq2, bounds=bounds, method="highs")
    if not r2.success:
        return {"solver": scipy_solver,
                "status": f"stage2 failed: {r2.message}"}
    x = r2.x
    labour = (x[0] * w["labour_h_per_ha"] + x[1] * p["labour_h_per_ha"])
    return _result(scipy_solver,
                   delivered=x[4] + x[5], shortage=x[6] + x[7],
                   production=x[2] + x[3], land=x[0] + x[1],
                   water=x[0] * w["water_m3_per_ha"] + x[1] * p["water_m3_per_ha"],
                   labour=labour)


def solve_cvxpy():
    """Same cross-solver LP (loss 0) via CVXPY. Backend recorded."""
    import cvxpy as cp

    w, p = CROPS
    area = cp.Variable(2, nonneg=True)
    prod = cp.Variable(2, nonneg=True)
    short = cp.Variable(2, nonneg=True)
    yields = cp.Constant([w["yield_t_per_ha"], p["yield_t_per_ha"]])
    demand = cp.Constant([w["demand_t"], p["demand_t"]])
    constraints = [
        prod == cp.multiply(yields, area),
        prod + short == demand,
        cp.sum(area) <= LAND_HA,
        w["water_m3_per_ha"] * area[0] + p["water_m3_per_ha"] * area[1] <= WATER_M3,
    ]
    prob = cp.Problem(cp.Minimize(cp.sum(short)), constraints)
    prob.solve(solver=cp.HIGHS)
    if prob.status not in ("optimal", "optimal_inaccurate"):
        return {"solver": "cvxpy (HiGHS backend)", "status": f"failed: {prob.status}"}
    # Stage 2: hold shortage, minimise production.
    prob2 = cp.Problem(cp.Minimize(cp.sum(prod)),
                       constraints + [cp.sum(short) <= float(prob.value) + 1e-6])
    prob2.solve(solver=cp.HIGHS)
    if prob2.status not in ("optimal", "optimal_inaccurate"):
        return {"solver": "cvxpy (HiGHS backend)", "status": f"stage2 failed: {prob2.status}"}
    return _result(f"cvxpy {cp.__version__} (HiGHS backend)",
                   delivered=float(sum(prod.value)), shortage=float(sum(short.value)),
                   production=float(sum(prod.value)), land=float(sum(area.value)),
                   water=float(w["water_m3_per_ha"] * area.value[0]
                               + p["water_m3_per_ha"] * area.value[1]))


def solve_cpmpy():
    """Same cross-solver LP (loss 0) via CPMpy, integer-scaled.

    CPMpy variables are integers, so areas are in 0.01 ha units and
    quantities in kg. Potato 20 t/ha = 200 kg per 0.01 ha; Wheat
    4 t/ha = 40 kg per 0.01 ha. Water: 12 / 20 m3 per 0.01 ha.
    Backend: HiGHS (highspy) if available, else the attempt and its
    exact error are returned as a blocked result — never faked.
    """
    from cpmpy import Model, intvar

    w, p = CROPS
    area = intvar(0, 10000, shape=2, name="area_centiha")  # 0.01 ha units
    prod_kg = intvar(0, 650000, shape=2, name="prod_kg")
    short_kg = intvar(0, 650000, shape=2, name="short_kg")
    model = Model(
        prod_kg[0] == 40 * area[0],
        prod_kg[1] == 200 * area[1],
        prod_kg[0] + short_kg[0] == 250_000,
        prod_kg[1] + short_kg[1] == 400_000,
        area[0] + area[1] <= 10_000,
        12 * area[0] + 20 * area[1] <= 100_000,
    )
    model.minimize(sum(short_kg))
    try:
        ok = model.solve(solver="highs")
    except Exception as exc:  # backend missing / solver error: report, don't fake
        return {"solver": "cpmpy (HiGHS backend requested)",
                "status": f"blocked: {type(exc).__name__}: {exc}"}
    if not ok:
        return {"solver": "cpmpy (HiGHS backend)", "status": "failed: no solution"}
    # Stage 2: hold shortage, minimise production.
    total_short = int(sum(short_kg.value()))
    model2 = Model(
        prod_kg[0] == 40 * area[0],
        prod_kg[1] == 200 * area[1],
        prod_kg[0] + short_kg[0] == 250_000,
        prod_kg[1] + short_kg[1] == 400_000,
        area[0] + area[1] <= 10_000,
        12 * area[0] + 20 * area[1] <= 100_000,
        sum(short_kg) == total_short,
    )
    model2.minimize(sum(prod_kg))
    ok2 = model2.solve(solver="highs")
    if not ok2:
        return {"solver": "cpmpy (HiGHS backend)", "status": "stage2 failed"}
    import cpmpy
    return _result(f"cpmpy {cpmpy.__version__} (HiGHS backend)",
                   delivered=sum(prod_kg.value()) / 1000.0,
                   shortage=sum(short_kg.value()) / 1000.0,
                   production=sum(prod_kg.value()) / 1000.0,
                   land=sum(area.value()) / 100.0,
                   water=(12 * area.value()[0] + 20 * area.value()[1]))


def check_totals(result: dict, expected: dict, tol: float = 0.02):
    """Compare a solver result to the analytic totals.

    Returns a ConstraintResult per total (PASS/FAIL) plus an overall
    PlanningResult. Non-finite or missing values -> UNKNOWN, never PASS.
    """
    from .statuses import ConstraintResult, InternalStatus, PlanningResult

    checks = []
    for key in ("delivered_t", "shortage_t", "production_t"):
        actual = result.get(key)
        exp = expected[key]
        if actual is None or not math.isfinite(actual):
            checks.append(ConstraintResult(
                f"opt-{key}", InternalStatus.UNKNOWN,
                f"{key}: no finite value returned by {result.get('solver')}",
                actual_value=actual, required_value=exp, unit="t"))
        elif abs(actual - exp) <= tol:
            checks.append(ConstraintResult(
                f"opt-{key}", InternalStatus.PASS,
                f"{key} {actual} t matches expected {exp} t (tol {tol})",
                actual_value=actual, required_value=exp, unit="t",
                evidence=[f"solver: {result.get('solver')}"]))
        else:
            checks.append(ConstraintResult(
                f"opt-{key}", InternalStatus.FAIL,
                f"{key} {actual} t != expected {exp} t (tol {tol})",
                actual_value=actual, required_value=exp, unit="t",
                evidence=[f"solver: {result.get('solver')}"]))
    return PlanningResult(scenario_id="synthetic-1-site-2-crop", checks=checks)
