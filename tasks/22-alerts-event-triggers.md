Title: Alerts – Event Triggers on New Transactions and Threshold Breaches

Context
- Proactive alerts on new transactions or min-balance threshold breaches.

Objective
- Add alert computation after ingest and on-demand when new data arrives.

Deliverables
- Logic that:
  - Detects when `min_balance` drops below threshold compared to last snapshot.
  - Flags large unplanned debit (>|X| configurable).
  - Detects commitment drift (amount/date) persisting ≥ 3 cycles; suggest update.
- Store alerts in a simple `alerts` table or include in digest payload.

Dependencies
- Tasks 07–09.

Implementation Notes
- Implement in `jobs/nightly_snapshot.py` or a dedicated `alerts/engine.py`.
- Keep thresholds in a config.

Acceptance Criteria
- Triggering conditions create alerts once; deduplicate on repeated runs.

Test Guidance
- Unit tests simulating conditions; integration test alerts list after an ingest.

Affected/Added Files
- New: `alerts/engine.py` (optional `alerts` table migration if persisted)
- Touch: jobs and API surface if needed to fetch alerts.

