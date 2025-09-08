Title: Forecast – Calendar Expansion (Deterministic)

Context
- Deterministic forecast is calendar-only: scheduled inflows, commitments, key spend events.

Objective
- Implement a pure function/module that builds a dated ledger from start→end using known items and policies.

Deliverables
- Module `forecast/calendar.py` with:
  - expand_calendar(start, end) → list[Entry] covering dated inflows/outflows with metadata (type, name, amount_cents, source_id, shift_applied, policy).
  - compute_balances(opening_balance_cents, entries) → dict[date→balance_cents].
- Support shift policies: AS_SCHEDULED | PREV_BUSINESS_DAY | NEXT_BUSINESS_DAY.
- Support flexible windows on commitments where applicable.

Dependencies
- Tasks 01, and data (commitments, scheduled_inflows, key_spend_events) present.

Implementation Notes
- Keep business-day logic simple (Mon–Fri). No holidays in v1.
- Entries must be stable/deterministic given the same DB state.

Acceptance Criteria
- Unit tests validate balance[t+1] equation per spec and shift behaviors.
- Determinism: identical inputs produce identical outputs.

Test Guidance
- Fixtures for weekend shifts, windowed bills, and key events.

Affected/Added Files
- New: `forecast/calendar.py`, `tests/test_forecast_calendar.py`

