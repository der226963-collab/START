"""Labour-domain input schema and stated-input policy (ISSUE-34, 2026-11-13).

The two unpaid-care figures are REQUIRED caller inputs, never
silently defaulted — the ISSUE-15 policy carried over from food:
a request that omits ``unpaid_care_hours_per_day_billion`` or
``women_share_unpaid_care_percent``, or passes explicit ``None``
for either, fails validation ("missing required field") and the
calculation returns INSUFFICIENT_INPUT. The caller states the
snapshot values it is using (the example loads them from the
versioned snapshot via ``contracts.plan_limits``); the domain
never loads the snapshot itself and never assumes a figure.

``paid_work_hours_per_week`` is OPTIONAL: a caller that does not
state a paid-work figure gets the long-hours check as UNKNOWN,
never PASS (the same boundless treatment food gives a missing
requirement). ``population`` is likewise OPTIONAL and is used ONLY
for per-person care hours when the caller explicitly supplies it;
no population is ever assumed. The two ``snapshot_paid_work_*``
fields are optional snapshot CONTEXT (the 2026 employed / all-adults
averages), echoed into metrics labelled as snapshot values — they
are never the caller's figure and never checked against the
threshold.
"""
REQUIRED_FOR_CARE = (
    "unpaid_care_hours_per_day_billion",
    "women_share_unpaid_care_percent",
)
# Numeric request fields a scenario may change (see
# LabourDomain.scenario_change_fields): every numeric field the
# request may carry.
NUMERIC_REQUEST_FIELDS = REQUIRED_FOR_CARE + (
    "paid_work_hours_per_week",
    "population",
    "snapshot_paid_work_hours_per_week_employed",
    "snapshot_paid_work_hours_per_week_all_adults",
)
OPTIONAL_FIELDS = (
    "geography", "period", "source_ids",
)
# Fields a labour-domain request may carry. Anything else is rejected
# by validate_inputs (ISSUE-12): a misspelled field (e.g.
# "paid_work_hours_per weak") must surface as a problem, never be
# silently ignored while the intended value is missing.
# "scenario_assumptions" is set by LabourDomain.scenario_request and
# read by calculate(); "scenario_id" is set by the generic
# DomainModule.scenario_request path — both are metadata, not inputs,
# and are allowed so scenario runs still validate.
ALLOWED_REQUEST_FIELDS = (
    NUMERIC_REQUEST_FIELDS
    + OPTIONAL_FIELDS
    + ("scenario_assumptions", "scenario_id")
)
# ISSUE-34: there are no silent defaults in this domain. The care
# figures, the paid-work figure and the population are all stated by
# the caller or absent — never assumed.
