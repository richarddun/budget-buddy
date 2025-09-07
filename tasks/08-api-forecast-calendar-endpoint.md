Title: API – GET /api/forecast/calendar

Context
- Expose deterministic forecast over a date range with optional buffer floor.

Objective
- Implement `GET /api/forecast/calendar?start=YYYY-MM-DD&end=YYYY-MM-DD&buffer_floor=5000`.

Deliverables
- Endpoint returns JSON with:
  - opening_balance_cents (sum of cleared balances across active accounts or provided strategy)
  - entries: dated items (type, name, amount_cents, source_id)
  - balances: date→balance_cents
  - min_balance_cents, min_balance_date

Dependencies
- Task 07 (calendar engine). Ensure FastAPI app routing file.

Implementation Notes
- Place route in `budget_health_api.py` or a new `api/forecast.py` and include router in `main.py`.
- Opening balance: for v1, compute from last known cleared transactions or a configured value. Document approach in response metadata.
- Respect `buffer_floor` in computed metadata (but don’t change balances).

Acceptance Criteria
- Request returns 200 with correct structure and deterministic numbers given fixed DB state.
- Input validation for dates; errors return 400 with message.

Test Guidance
- Unit/integration test with seeded DB and fixed start/end, asserting min_balance and dates.

Affected/Added Files
- New: `api/forecast.py`
- Touch: `main.py` to include router.

