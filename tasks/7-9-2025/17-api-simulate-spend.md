Title: API – POST /api/forecast/simulate-spend

Context
- Users ask “Can I spend X today?” The API should deterministically answer.

Objective
- Implement `POST /api/forecast/simulate-spend` {date, amount_cents, mode} returning safe/unsafe, new min balance, tight days, and max_safe_today.

Deliverables
- Endpoint that:
  - Runs deterministic forecast from Task 07 using selected mode (deterministic or blended baseline for reference only; decision is against buffer floor).
  - Applies the hypothetical spend on given date and recomputes min balance.
  - Uses binary search to compute `max_safe_today`.

Dependencies
- Tasks 07–08 (and optionally 16 if blending referenced).

Implementation Notes
- Keep within performance budgets; search in integer cents.
- Return clear reasoning notes in JSON.

Acceptance Criteria
- Given a seeded DB, endpoint returns consistent safe/unsafe decisions and correct max_safe_today.

Test Guidance
- Unit test the binary search; integration test full endpoint.

Affected/Added Files
- Touch: `api/forecast.py` to add POST route.

