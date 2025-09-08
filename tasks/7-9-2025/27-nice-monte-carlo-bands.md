Title: Nice-to-Have – Monte Carlo P10/P90 Bands (Flagged)

Context
- Optional enhancement to visualize stochastic variability; behind a feature flag.

Objective
- Add an experimental endpoint to compute Monte Carlo bands using simple draws around μ/σ daily.

Deliverables
- Endpoint `GET /api/forecast/monte-carlo?...` returning P10/P90 bands.
- Feature flag to disable by default.

Dependencies
- Tasks 15–16.

Implementation Notes
- Limit iterations; seed RNG for reproducibility when flag enabled.
- Keep separate from deterministic baseline.

Acceptance Criteria
- Returns bands only when flag enabled; otherwise 404 or disabled.

Affected/Added Files
- Touch: `api/forecast.py`, config for feature flag.

