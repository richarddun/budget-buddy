Title: Questionnaire – Deterministic Query Endpoints

Context
- Lender-style deterministic queries over a chosen period with evidence IDs.

Objective
- Implement endpoints under `/api/q/*` for the listed queries.

Deliverables
- Endpoints:
  - GET /api/q/monthly-total-by-category
  - GET /api/q/monthly-average-by-category
  - GET /api/q/active-loans
  - GET /api/q/summary/income
  - GET /api/q/subscriptions
  - GET /api/q/category-breakdown
  - GET /api/q/supporting-transactions
  - GET /api/q/household-fixed-costs
- Each returns `{value_cents, window_start, window_end, method, evidence_ids[]}` or typed rows as specified.

Dependencies
- Tasks 01, 05.

Implementation Notes
- Implement as SQL views/queries in a module `q/queries.py` and expose via `api/q.py`.
- Use `question_category_alias` for typeahead and alias resolution.
- Ensure pagination for evidence transactions.

Acceptance Criteria
- Each endpoint returns deterministic values on fixtures; includes method and evidence_ids.

Test Guidance
- Unit/integration tests per query against seeded fixtures.

Affected/Added Files
- New: `q/queries.py`, `api/q.py`, `tests/test_q_endpoints.py`

