Title: API – GET /api/forecast/blended and UI Toggle

Context
- Blended forecast overlays bands around deterministic baseline.

Objective
- Implement `GET /api/forecast/blended?...&mu_daily=...&sigma_daily=...&weekday_mult=[...]&band_k=0.8` and add a UI toggle.

Deliverables
- Endpoint combining deterministic balances with expected variable spend subtraction and bands.
- UI toggle to switch between Deterministic and Blended.

Dependencies
- Tasks 08, 15, 11.

Implementation Notes
- If parameters are not provided, compute from stats module (Task 15).
- Return baseline_blended and bands (lower/upper) per date.
- No RNG; all deterministic calculations.

Acceptance Criteria
- API returns correct structure; toggling updates chart with a shaded band.

Test Guidance
- Integration test: fixed mu/sigma/mults yields expected curves.

Affected/Added Files
- Touch: `api/forecast.py`, `templates/budget_health.html` or JS to add toggle.

