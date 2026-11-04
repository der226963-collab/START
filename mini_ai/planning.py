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


def weather_summary(rows, warming_degrees=1.0):
    """Weather vs climate, with a simple moisture calculation.

    warming_degrees is an input to the 7-percent-per-degree rule,
    not a forecast. It shows how a warmer atmosphere can hold
    more moisture, which is why heavy rain can become more intense.
    """
    anomaly_1951 = get(rows, "global_temperature_anomaly_vs_1951_1980", 2024)
    anomaly_preindustrial = get(rows, "global_temperature_anomaly_vs_1850_1900", 2024)
    moisture_per_degree = get(rows, "atmospheric_moisture_increase_per_degree", 2023)
    return {
        "weather": "State of the atmosphere at a place and time: temperature, precipitation, wind, humidity, pressure, cloud cover.",
        "climate": "Pattern of weather over a long time, usually 30 years (WMO normals, e.g. 1991-2020).",
        "global_temperature_anomaly_2024_vs_1951_1980_celsius": anomaly_1951,
        "global_temperature_anomaly_2024_vs_1850_1900_celsius": anomaly_preindustrial,
        "record_monthly_streak_months_jun2023_aug2024": get(rows, "record_monthly_temperature_streak_months", 2024),
        "moisture_increase_percent_for_input_warming": round(moisture_per_degree * warming_degrees, 1),
        "warning": "A single hot day or cold week is weather, not climate. A forecast is a probability and a range, not a certainty. Weather data plans days and weeks; climate data plans seasons, years, and infrastructure.",
    }


def soil_summary(rows):
    """Soil and nutrient balance, from real anchors plus a teaching example.

    The teaching example is labelled as such: 100 units of nitrogen
    applied, 50 taken up by crops, 30 lost, 20 left in soil. It shows
    the balance arithmetic, it is not a real field measurement.
    """
    degraded = get(rows, "global_soils_degraded_percent", 2025)
    p_applied = get(rows, "phosphorus_application_to_cropland", 2025)
    p_boundary = get(rows, "phosphorus_regional_boundary", 2025)
    n_fixation = get(rows, "nitrogen_fixation", 2025)
    return {
        "food_grown_in_soil_percent": get(rows, "food_grown_in_soil_percent", 2025),
        "global_soils_degraded_percent": degraded,
        "phosphorus_application_tg_per_year": p_applied,
        "phosphorus_regional_boundary_tg_per_year": p_boundary,
        "phosphorus_excess_tg_per_year": round(p_applied - p_boundary, 1),
        "phosphorus_ratio_to_boundary": round(p_applied / p_boundary, 2),
        "nitrogen_fixation_tg_per_year": n_fixation,
        "nitrogen_note": "More than twice its boundary in Planetary Health Check 2025, high-risk zone. Exact N boundary not in this snapshot, so no N surplus is calculated here.",
        "teaching_nutrient_balance_example": {
            "nitrogen_applied_units": 100,
            "nitrogen_crop_uptake_units": 50,
            "nitrogen_losses_units": 30,
            "nitrogen_soil_change_units": 20,
            "equation": "balance = inputs - outputs - losses; 100 - 50 - 30 = 20",
        },
        "warning": "Global nutrient excess and local nutrient deficit exist at the same time. A global balance does not tell a farmer what a specific field needs. Test soil, apply only what is needed, and recycle nutrients.",
    }


def systems_summary(rows):
    """Water, land, housing, health, transport, and labour at global scale.

    All ratios below are simple divisions of snapshot values, shown
    so a reader can check them. They are global averages, not local
    allocations, and they do not decide anything.
    """
    population_billion = get(rows, "world_population", 2024)
    population = population_billion * 1_000_000_000
    ag_land_mha = get(rows, "global_agricultural_land", 2023)
    cropland_mha = get(rows, "global_cropland", 2023)
    return {
        "agricultural_land_hectares_per_person": round(ag_land_mha * 1_000_000 / population, 3),
        "cropland_hectares_per_person": round(cropland_mha * 1_000_000 / population, 3),
        "agriculture_share_freshwater_withdrawals_percent": get(rows, "agriculture_share_freshwater_withdrawals", 2025),
        "water_share_uncertainty_note": "FAO/UNESCO report about 70 percent; a 2025 PNAS Nexus study warns the possible range is 45 to 90 percent, central 70 to 85 percent. Do not quote 70 percent as exact.",
        "people_lacking_drinking_water_percent_of_population": round(100 * get(rows, "people_lacking_safely_managed_drinking_water", 2022) * 1_000_000 / population, 1),
        "people_lacking_adequate_housing_million": get(rows, "people_lacking_adequate_housing", 2026),
        "people_in_slums_million_2024": get(rows, "people_in_slums_informal_settlements", 2024),
        "buildings_share_energy_percent": get(rows, "buildings_share_global_energy", 2023),
        "buildings_share_co2_percent": get(rows, "buildings_share_global_co2", 2023),
        "heat_related_deaths_per_year_2000_2019": get(rows, "heat_related_deaths_per_year", 2019),
        "unpaid_care_hours_per_day_billion": get(rows, "unpaid_care_hours_per_day", 2018) / 1000,
        "women_share_unpaid_care_percent": get(rows, "women_share_unpaid_care_work", 2018),
        "transport_co2_million_tonnes_2023": get(rows, "transport_co2", 2023),
        "road_transport_co2_million_tonnes_2023_approx": round(get(rows, "transport_co2", 2023) * get(rows, "road_share_transport_co2", 2023) / 100, 1),
        "paid_work_hours_per_week_employed": get(rows, "paid_work_hours_per_week_employed", 2026),
        "warning": "Global averages hide distribution by region, income, gender, and household. Use them for scale, then get consented local data for a real plan.",
    }


def climate_trend(path="data/climate_time_series_full.csv"):
    """Simple trend check on the full GISTEMP/NOAA series.

    Compares mean temperature anomaly in 1880-1899 with 2000-2025,
    and CO2 in 1959 with 2025. This is a description of the series,
    not a forecast and not a predictive model.
    """
    import csv

    rows = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    early = [float(r["gistemp_anomaly_c_vs_1951_1980"]) for r in rows if 1880 <= int(r["year"]) <= 1899]
    late = [float(r["gistemp_anomaly_c_vs_1951_1980"]) for r in rows if 2000 <= int(r["year"]) <= 2025]
    co2 = {int(r["year"]): float(r["mauna_loa_co2_ppm"]) for r in rows if r["mauna_loa_co2_ppm"]}
    return {
        "years_in_series": len(rows),
        "first_year": int(rows[0]["year"]),
        "last_year": int(rows[-1]["year"]),
        "mean_anomaly_1880_1899_c": round(sum(early) / len(early), 3),
        "mean_anomaly_2000_2025_c": round(sum(late) / len(late), 3),
        "anomaly_change_c": round(sum(late) / len(late) - sum(early) / len(early), 3),
        "co2_1959_ppm": co2[1959],
        "co2_2025_ppm": co2[2025],
        "co2_increase_ppm_1959_2025": round(co2[2025] - co2[1959], 2),
        "warning": "Annual means only. A trend in the past does not by itself predict the future, and it does not allocate anything.",
    }


def pilot_summary(path="data/local_pilot_example.csv"):
    """Totals for the SYNTHETIC pilot example only.

    This function refuses to present the example as real data.
    Replace the file with consented, anonymised real data only
    after the checklist in local_pilot_template.md is met.
    """
    import csv

    rows = list(csv.DictReader(open(path, newline="")))
    if any("SYNTH" not in r["household_id"] for r in rows):
        raise ValueError("Pilot file contains non-synthetic rows; check consent before using it.")
    return {
        "status": "SYNTHETIC EXAMPLE ONLY — NOT A REAL COMMUNITY",
        "households": len(rows),
        "people": sum(int(r["people_in_household"]) for r in rows),
        "land_hectares": sum(float(r["land_hectares_available"]) for r in rows),
        "food_kcal_needed_per_day": sum(int(r["food_kcal_needed_per_day"]) for r in rows),
        "energy_kwh_needed_per_year": sum(int(r["energy_kwh_needed_per_year"]) for r in rows),
        "care_hours_per_week": sum(int(r["care_hours_per_week"]) for r in rows),
        "households_with_inadequate_housing": sum(1 for r in rows if r["housing_adequate"] == "no"),
        "warning": "Do not use these totals for a real allocation. They test code shape only.",
    }


def run_plan(path="data/real_planning_data.csv"):
    rows = load_snapshot(path)
    return {
        "source": "data/real_planning_data.csv, see data/real_planning_sources.md",
        "layer": "calculation only, not a language model output, not a decision",
        "food": food_balance(rows),
        "weather": weather_summary(rows),
        "soil": soil_summary(rows),
        "systems": systems_summary(rows),
        "climate_trend": climate_trend(),
        "pilot_example": pilot_summary(),
        "energy_and_materials": energy_and_materials(rows),
        "cereals_2023_million_tonnes": get(rows, "global_cereals_production", 2023),
        "primary_crops_2023_million_tonnes": get(rows, "global_primary_crops_production", 2023),
    }


if __name__ == "__main__":
    print(json.dumps(run_plan(), indent=2))
