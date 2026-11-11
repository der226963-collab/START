# Verification scope

## What the verifier checks

- Calculation and check statuses are recognized.
- Constraint result structures are valid.
- Every completed calculation has at least one evaluated constraint.
- The claimed overall status matches the status derived from all listed constraints.
- A non-completed calculation cannot claim `PASS`.
- Invalid constraint status values are errors, not silently ignored.
- For the food domain, the verifier independently recomputes the core balance equations from the original request and compares the resulting metrics and adequacy status.

## Verification states

- `VERIFIED`: the implemented independent checks passed.
- `FAILED`: one or more checks failed.
- `PARTIALLY_VERIFIED`: structural/status checks passed but no independent domain arithmetic verifier is implemented.
- `NOT_VERIFIABLE`: calculation was not completed or could not be independently checked.

`verified` is true only for `VERIFIED`. This flag does **not** mean the input sources are true or that the model is socially/ecologically adequate.

## Food arithmetic cross-check

The verifier re-derives:

```text
effective domestic supply = domestic supply × (1 − losses fraction)
total available = effective domestic supply + imports
per-capita surplus = total available − requirement
annual aggregate balance = per-capita surplus × population × 365
```

The verifier implementation is separate from the food calculation function to reduce the chance that one arithmetic defect is simply repeated by the checker. Both still share the same stated model assumptions and therefore do not constitute independent empirical validation.

## Not checked

- Source authenticity, measurement quality or sampling bias
- Whether the supplied requirement is normatively or scientifically appropriate
- Household-level food access or distribution
- Model completeness or causal validity
- Cross-domain ecological or material feasibility
- Governance legitimacy or consent
