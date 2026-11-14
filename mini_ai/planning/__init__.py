"""Planning calculation layer, as a package.

This module is NOT MiniGPT, and MiniGPT is NOT this module.
Language helps explain a plan. This package checks a plan with
arithmetic. People in assembly decide a plan.

``core`` holds the calculations (snapshot, food, soil, weather,
systems, climate, pilot, plan-limit checks). ``models`` holds the
typed result shapes (``CheckStatus``, ``ConstraintResult``,
``PlanningResult``). Everything public is re-exported here so
``from mini_ai.planning import check_plan_limits`` keeps working
exactly as it did when this was a single ``planning.py`` module.
"""

from .core import (
    CO2_INTENSITY_G_PER_KWH,
    backtest_climate,
    check_plan_limits,
    climate_trend,
    electricity_allocation,
    energy_and_materials,
    food_balance,
    get,
    load_snapshot,
    pilot_summary,
    run_plan,
    soil_summary,
    systems_summary,
    weather_summary,
)
from .models import CheckStatus, ConstraintResult, PlanningResult

__all__ = [
    "CO2_INTENSITY_G_PER_KWH",
    "backtest_climate",
    "check_plan_limits",
    "climate_trend",
    "electricity_allocation",
    "energy_and_materials",
    "food_balance",
    "get",
    "load_snapshot",
    "pilot_summary",
    "run_plan",
    "soil_summary",
    "systems_summary",
    "weather_summary",
    "CheckStatus",
    "ConstraintResult",
    "PlanningResult",
]
