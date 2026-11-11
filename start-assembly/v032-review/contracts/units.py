"""Small explicit unit registry for common planning quantities.

This is not a universal units package. Unknown units are rejected rather than
silently treated as compatible. Extend the registry deliberately as domains grow.
"""
from __future__ import annotations
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class UnitDefinition:
    dimension: str
    factor_to_base: float


_UNITS = {
    "1": UnitDefinition("dimensionless", 1.0),
    "person": UnitDefinition("people", 1.0),
    "people": UnitDefinition("people", 1.0),
    "kg": UnitDefinition("mass", 1.0),
    "g": UnitDefinition("mass", 0.001),
    "tonne": UnitDefinition("mass", 1000.0),
    "t": UnitDefinition("mass", 1000.0),
    "L": UnitDefinition("volume", 0.001),
    "m3": UnitDefinition("volume", 1.0),
    "m²": UnitDefinition("area", 1.0),
    "ha": UnitDefinition("area", 10000.0),
    "kcal": UnitDefinition("energy", 1.0),
    "Mcal": UnitDefinition("energy", 1000.0),
    "kWh": UnitDefinition("energy", 860.4206501),
    "MWh": UnitDefinition("energy", 860420.6501),
    "kcal/capita/day": UnitDefinition("food_energy_rate_per_capita", 1.0),
    "kcal/person/day": UnitDefinition("food_energy_rate_per_capita", 1.0),
    "kcal/day": UnitDefinition("food_energy_rate_per_capita", 1.0),
    "m3/day": UnitDefinition("volume_rate", 1.0),
    "L/day": UnitDefinition("volume_rate", 0.001),
    "kg/day": UnitDefinition("mass_rate", 1.0),
    "tonne/day": UnitDefinition("mass_rate", 1000.0),
    "kWh/day": UnitDefinition("energy_rate", 1.0),
    "MWh/day": UnitDefinition("energy_rate", 1000.0),
}


def unit_definition(unit: str) -> UnitDefinition | None:
    return _UNITS.get(unit)


def are_compatible(source: str, target: str) -> bool:
    a, b = unit_definition(source), unit_definition(target)
    return bool(a and b and a.dimension == b.dimension)


def convert(value: float, source: str, target: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("value must be a finite number")
    a, b = unit_definition(source), unit_definition(target)
    if not a or not b:
        raise ValueError(f"unknown unit: {source if not a else target}")
    if a.dimension != b.dimension:
        raise ValueError(f"incompatible units: {source} and {target}")
    # ISSUE-47 (2026-11-11): the multiplication/division can overflow
    # to inf (e.g. convert(1e308, "tonne", "g") used to return inf).
    # An infinite result is never returned silently; it raises
    # ValueError like every other convert error. Callers that must
    # stay total (Constraint.evaluate) catch ValueError and return
    # UNKNOWN, matching Rust/Julia, which return UNKNOWN/NON_FINITE
    # for the same conversion instead of ever passing an infinite
    # normalised value.
    result = float(value) * a.factor_to_base / b.factor_to_base
    if not math.isfinite(result):
        raise ValueError("converted value must be finite")
    return result
