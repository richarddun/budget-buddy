Title: Jobs – Nightly Forecast Snapshot and Digest Payload

Context
- After each nightly sync, compute forecast(s) and store a snapshot; power dashboard/digest.

Objective
- Add a scheduled job that runs after ingestion to produce and store `forecast_snapshot` and a digest JSON.

Deliverables
- Function `jobs/nightly_snapshot.py` that:
  - Builds calendar forecast for a default horizon (e.g., 120 days).
  - Stores `forecast_snapshot` (payload, min_balance, dates).
  - Computes digest: current balance, safe-to-spend today, next cliff date, min balance/date, top commitments next 14 days, upcoming key events within lead window.
- Wire into `jobs/daily_ingestion.py` or scheduler loop in `main.py`.

Dependencies
- Tasks 07–08.

Implementation Notes
- Use the same opening-balance strategy as API for consistency.
- Persist timestamp and mark UI as “stale” if job fails on a given day.

Acceptance Criteria
- On scheduler run, a new `forecast_snapshot` row is created and digest is derivable.
- Failures do not break startup; next run overwrites with fresh snapshot.

Test Guidance
- Integration test: seed DB, run job, assert snapshot row and digest fields.

Affected/Added Files
- New: `jobs/nightly_snapshot.py`
- Touch: `main.py` or `jobs/daily_ingestion.py` to call it post-ingest.

