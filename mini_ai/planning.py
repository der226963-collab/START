"""Separate planning calculation layer.

This module is NOT MiniGPT, and MiniGPT is NOT this module.
Language helps explain a plan. This module checks a plan with
arithmetic. People in assembly decide a plan.

It uses only the aggregated global snapshot in
data/real_planning_data.csv, plus assumptions stated explicitly
in the code and in the output. It does not allocate to a real
community, and a global average does not prove anyone is fed.
"""

import csv
import json
from pathlib import Path


def load_snapshot(path="data/real_planning_data.csv"):
    """Load the real planning snapshot as a dict keyed by indicator+year."""
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["value"] = float(row["value"])
            rows.append(row)
    return rows


def get(rows, indicator, year):
    for row in rows:
        if row["indicator"] == indicator and int(row["year"]) == year:
            return row["value"]
    raise KeyError(f"{indicator} {year} not found in snapshot")


def food_balance(rows, planning_need_kcal_per_day=2500):
    """Global food energy balance: supply vs a stated planning need.

    planning_need_kcal_per_day is an assumption, not a FAO figure.
    2500 is a round planning figure, above the WFP-style 2100
    minimum and below the 2022 global supply average.
    """
    population_billion = get(rows, "world_population", 2024)
    supply = get(rows, "global_food_supply_dietary_energy", 2022)
    population = population_billion * 1_000_000_000
    supply_kcal_per_year = supply * population * 365
    need_kcal_per_year = planning_need_kcal_per_day * population * 365
    return {
        "population_billion": population_billion,
        "supply_kcal_per_capita_per_day_2022": supply,
        "planning_need_kcal_per_capita_per_day_assumption": planning_need_kcal_per_day,
        "supply_kcal_per_year_trillion": round(supply_kcal_per_year / 1e12, 1),
        "need_kcal_per_year_trillion": round(need_kcal_per_year / 1e12, 1),
        "surplus_kcal_per_capita_per_day": round(supply - planning_need_kcal_per_day, 1),
        "surplus_percent_of_need": round(100 * (supply - planning_need_kcal_per_day) / planning_need_kcal_per_day, 1),
        "warning": "Global average only. A surplus on average does not mean every person is fed. Real allocation must be per region and per household, with distribution, waste, feed, and stock separated.",
    }


# Lifecycle CO2 intensities, g CO2 per kWh, IPCC median-style
# illustrative values, stated here so they can be challenged.
# They are NOT in the real snapshot CSV, and they are NOT
# real-time grid data.
CO2_INTENSITY_G_PER_KWH = {
    "coal": 820,
    "gas": 490,
    "solar": 45,
    "wind": 11,
    "hydro": 24,
    "nuclear": 12,
}


def electricity_allocation(demand_twh, mix):
    """Allocate electricity demand across sources, compute CO2.

    mix is a dict source -> share (0 to 1), summing to 1.
    Returns total CO2 in million tonnes and per-source TWh.
    """
    if abs(sum(mix.values()) - 1.0) > 0.001:
        raise ValueError("Mix shares must sum to 1")
    allocation = {}
    total_co2_mt = 0.0
    for source, share in mix.items():
        twh = demand_twh * share
        co2_mt = twh * 1e9 * CO2_INTENSITY_G_PER_KWH[source] / 1e12
        allocation[source] = {"twh": round(twh, 1), "co2_million_tonnes": round(co2_mt, 1)}
        total_co2_mt += co2_mt
    return {"demand_twh": demand_twh, "mix": mix, "allocation": allocation, "total_co2_million_tonnes": round(total_co2_mt, 1)}


def energy_and_materials(rows):
    """Real-anchored engineering summary from the snapshot."""
    renewable_electricity = get(rows, "renewable_share_of_electricity", 2023)
    renewable_primary = get(rows, "renewable_share_of_primary_energy", 2023)
    capacity_added = get(rows, "renewable_capacity_added", 2023)
    steel = get(rows, "global_steel_production", 2023)
    steel_co2 = get(rows, "global_steel_co2", 2023)
    cement_co2 = get(rows, "global_cement_co2", 2023)
    # Illustrative demand: 30,000 TWh is the order of magnitude
    # for world electricity generation in 2022-2023 in the sources
    # searched, used here only to show the allocation arithmetic.
    demand_twh = 30000
    # Use only sources with stated intensities for the CO2 total.
    low_carbon_mix = {"coal": 0.10, "gas": 0.15, "solar": 0.30, "wind": 0.20, "hydro": 0.15, "nuclear": 0.10}
    current_mix = {"coal": 0.36, "gas": 0.23, "solar": 0.05, "wind": 0.08, "hydro": 0.15, "nuclear": 0.13}
    return {
        "renewable_share_of_electricity_2023_percent": renewable_electricity,
        "renewable_share_of_primary_energy_2023_percent": renewable_primary,
        "renewable_capacity_added_2023_gw": capacity_added,
        "note_on_shares": "Electricity share and primary energy share have different denominators. Do not mix them.",
        "steel_production_2023_million_tonnes": steel,
        "steel_co2_2023_million_tonnes": steel_co2,
        "cement_co2_2023_million_tonnes": cement_co2,
        "steel_plus_cement_co2_million_tonnes": steel_co2 + cement_co2,
        "electricity_example_demand_twh": demand_twh,
        "electricity_example_current_mix_co2": electricity_allocation(demand_twh, current_mix),
        "electricity_example_low_carbon_mix_co2": electricity_allocation(demand_twh, low_carbon_mix),
        "warning": "Electricity mixes in this example are illustrative shares summing to 1, not a measured 2023 grid mix. Intensities are lifecycle medians, not real-time plant data. The point is the arithmetic: shifting share to low-intensity sources cuts total CO2 for the same demand.",
    }


def run_plan(path="data/real_planning_data.csv"):
    rows = load_snapshot(path)
    return {
        "source": "data/real_planning_data.csv, see data/real_planning_sources.md",
        "layer": "calculation only, not a language model output, not a decision",
        "food": food_balance(rows),
        "energy_and_materials": energy_and_materials(rows),
        "cereals_2023_million_tonnes": get(rows, "global_cereals_production", 2023),
        "primary_crops_2023_million_tonnes": get(rows, "global_primary_crops_production", 2023),
    }


if __name__ == "__main__":
    print(json.dumps(run_plan(), indent=2))
