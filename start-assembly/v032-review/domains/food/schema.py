"""Food-domain input schema and stated-input policy (ISSUE-15, 2026-11-11).

``imports_kcal_per_capita_per_day`` and ``losses_fraction`` are REQUIRED
inputs, not optionals with a silent default. They used to be defaulted
to 0.0 as "explicit assumptions" (EXPLICIT_ZERO_ASSUMPTIONS, ISSUE-13);
that policy is removed: a request that omits either field, or passes
explicit ``None`` for it, fails validation ("missing required field")
and the calculation returns INSUFFICIENT_INPUT. Stating 0.0 explicitly
is allowed and means "no imports" / "no losses" — the caller, not the
domain, asserts that. See docs/ARCHITECTURE.md, "Food-energy formula
(ISSUE-15)", for why: the v0.3.2 formula only agrees with v0.3.1's
``surplus = supply - need`` when losses are 0 and imports are 0, so
silently assuming those values would silently reproduce the old
formula's answer while claiming the new model's.
"""
REQUIRED_FOR_AVAILABILITY = (
    "population",
    "supply_kcal_per_capita_per_day",
    "requirement_kcal_per_capita_per_day",
    "imports_kcal_per_capita_per_day",
    "losses_fraction",
)
OPTIONAL_FIELDS = (
    "geography", "period", "source_ids",
)
# Fields a food-domain request may carry. Anything else is rejected
# by validate_inputs (ISSUE-12): a misspelled field (e.g.
# "suply_kcal_per_capita_per_day") must surface as a problem, never
# be silently ignored while the correctly-spelled default is used.
# "scenario_assumptions" is set by FoodDomain.scenario_request and
# read by calculate(); "scenario_id" is set by the generic
# DomainModule.scenario_request path — both are metadata, not inputs,
# and are allowed so scenario runs still validate. No caller in this
# tree passes any other field (checked by grep before enforcing).
ALLOWED_REQUEST_FIELDS = (
    REQUIRED_FOR_AVAILABILITY
    + OPTIONAL_FIELDS
    + ("scenario_assumptions", "scenario_id")
)
# ISSUE-15: there are no silent defaults left in this domain. The
# former EXPLICIT_ZERO_ASSUMPTIONS dict (imports/losses assumed 0.0)
# is deleted, not kept as an empty dict: any code still importing it
# must fail loudly instead of silently finding a default to apply.
