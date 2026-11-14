"""Nutrients-domain input schema and stated-input policy (ISSUE-34, 2026-11-13).

One domain, ``nutrients``, covering phosphorus AND nitrogen. The two
nutrients share one balance shape — ``soil change = inputs - uptake -
losses`` — and one request shape, so they are one module, not two:
splitting them would duplicate the schema, the balance, the
evaluation and the scenario allow-lists for two nutrients that are
always reported together in the snapshot (soil_summary in
``domains/compat_v031.py`` reports them side by side).

Stated-input policy, same rule as food (ISSUE-15): uptake and losses
are REQUIRED inputs, not optionals with a silent default. A request
that states an applied/fixation amount but omits uptake or losses, or
passes explicit ``None`` for either, fails validation ("missing
required field") and the calculation returns INSUFFICIENT_INPUT.
Stating 0.0 explicitly is allowed and means "no uptake" / "no
losses" — the caller, not the domain, asserts that. The snapshot
carries no uptake/losses values at all, so no balance can be
computed from the snapshot alone; see
``examples/global_nutrient_balance.py``.

Phosphorus boundary: the 6.2 Tg/yr regional boundary is a STORED
snapshot value (``contracts.plan_limits``), not a caller input. A
request may carry ``phosphorus_boundary_tg_per_year`` only as a
confirmation of the stored bound — a value that differs from the
stored bound is a validation problem (wrong-bound detection, same
rule as ``plan_limits`` overrides), never silently applied.

Nitrogen boundary: there is NONE. The snapshot records nitrogen
fixation 165 Tg/yr as "more than twice its boundary" (Planetary
Health Check 2025, high-risk zone) but stores no exact boundary
value, so no ``nitrogen_boundary_tg_per_year`` request field exists
at all: there is nothing a caller could correctly state, and a
caller-supplied nitrogen bound would be an invented figure.
"""
# Per-nutrient field groups. A request states at least one nutrient's
# input field (applied for phosphorus, fixation for nitrogen); for
# each nutrient whose input is stated, its uptake and losses are
# required too. A nutrient with no input stated is simply absent —
# its uptake/losses, if supplied without the input, are a problem
# (a half-stated balance), not ignored.
PHOSPHORUS_FIELDS = (
    "phosphorus_applied_tg_per_year",
    "phosphorus_uptake_tg_per_year",
    "phosphorus_losses_tg_per_year",
)
NITROGEN_FIELDS = (
    "nitrogen_fixation_tg_per_year",
    "nitrogen_uptake_tg_per_year",
    "nitrogen_losses_tg_per_year",
)
# Numeric request fields a scenario may change (the domain's
# scenario_change_fields). The boundary is numeric and changeable
# only in the confirmation sense: a scenario proposing a boundary
# that differs from the stored bound fails validation at run time.
NUMERIC_REQUEST_FIELDS = PHOSPHORUS_FIELDS + NITROGEN_FIELDS + (
    "phosphorus_boundary_tg_per_year",
)
OPTIONAL_FIELDS = (
    "geography", "period", "source_ids",
)
# Fields a nutrients-domain request may carry. Anything else is
# rejected by validate_inputs (ISSUE-12): a misspelled field (e.g.
# "phosphorus_aplied_tg_per_year") must surface as a problem, never
# be silently ignored while the correctly-spelled value is missing.
# "scenario_assumptions" is set by NutrientsDomain.scenario_request
# and read by calculate(); "scenario_id" is set by the generic
# DomainModule.scenario_request path — both are metadata, not inputs,
# and are allowed so scenario runs still validate.
ALLOWED_REQUEST_FIELDS = (
    NUMERIC_REQUEST_FIELDS
    + OPTIONAL_FIELDS
    + ("scenario_assumptions", "scenario_id")
)
# ISSUE-34: there are no silent defaults in this domain. Uptake and
# losses are never assumed 0.0, and there is no nitrogen boundary to
# default to — a missing nitrogen bound is UNKNOWN by design, never
# a zero or an invented figure.
