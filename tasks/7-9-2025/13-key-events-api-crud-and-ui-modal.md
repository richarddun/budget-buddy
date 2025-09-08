Title: Key Spending Events – CRUD API and UI Modal

Context
- Users add birthdays/holidays/etc. with optional repeat and lead_time.

Objective
- Build CRUD API and a simple UI modal to add/edit/delete key spend events.

Deliverables
- API routes:
  - GET /api/key-events?from=...&to=...
  - POST /api/key-events (upsert): {id?, name, event_date, repeat_rule?, planned_amount_cents, category_id, lead_time_days, shift_policy?, account_id}
  - DELETE /api/key-events/{id}
- Minimal UI modal for add/edit with validation.

Dependencies
- Task 01 (DB), Task 08 (calendar API uses these to mark), Task 11 (markers).

Implementation Notes
- Writes require CSRF/session auth; validate inputs.
- Do not allow LLM direct DB writes; only via API with explicit confirmation.

Acceptance Criteria
- Create/update/delete flow works; GET filters by date range.
- Invalid data returns 400 with message.

Test Guidance
- API tests covering CRUD and date filtering.

Affected/Added Files
- New: `api/key_events.py`
- Touch: `main.py` to include router; `templates` for UI modal.

