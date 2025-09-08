Title: Blended – Compute μ/σ and Weekday Multipliers

Context
- Optional blended forecast subtracts expected variable spend using μ_daily and weekday multipliers.

Objective
- Compute μ_daily, σ_daily, and weekday_multipliers from last 90–180 days of variable spending.

Deliverables
- Module `forecast/blended_stats.py` with functions:
  - compute_daily_stats(transactions, window_days=180) → (mu_cents, sigma_cents)
  - compute_weekday_multipliers(transactions, window_days=180) → list[7] normalized to avg=1.0
- Exclude known commitments/key events from variable-spend sample.

Dependencies
- Tasks 01, 07; access to transactions and category map to identify variable spend.

Implementation Notes
- Keep deterministic; no RNG.
- Handle sparse data by falling back to neutral multipliers (all 1.0) and mu=0, sigma=0.

Acceptance Criteria
- Given a seeded dataset, functions return stable values and normalize multipliers.

Test Guidance
- Unit tests with synthetic datasets covering weekdays and variance.

Affected/Added Files
- New: `forecast/blended_stats.py`, `tests/test_blended_stats.py`

