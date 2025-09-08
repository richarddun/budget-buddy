Title: QA – Test Suite and Performance Budgets

Context
- Ensure correctness, determinism, and performance targets.

Objective
- Build out unit, integration, and UI tests per spec; verify performance budgets.

Deliverables
- Tests for ingestion idempotence, forecast math, shift policies, simulate-spend, questionnaire queries, packs, exports, alerts.
- Performance checks: forecast ≤150ms for 120-day horizon; dashboard JSON ≤200KB.

Dependencies
- Broadly after core features (Tasks 03–23).

Implementation Notes
- Use pytest; isolate DB via temp files.
- For UI tests, choose Playwright or similar; mock API.

Acceptance Criteria
- Test suite green locally; key invariants pass.

Test Guidance
- Add fixtures with synthetic dataset (salary, subscriptions, utilities variance, loan, birthdays, Christmas, edge cases).

Affected/Added Files
- New/Touch: `tests/` as needed, CI config if applicable.

