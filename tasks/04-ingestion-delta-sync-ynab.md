Title: Ingestion – Delta Sync with YNAB (`--delta`)

Context
- After backfill, keep data current incrementally using YNAB `since_date`/`server_knowledge`.

Objective
- Implement `budgetctl ingest ynab --delta` that fetches only new/changed transactions and upserts.

Deliverables
- Delta function that:
  - Reads last cursor from `source_cursor` (source='ynab').
  - Fetches changes using YNAB-supported delta mechanism (by date or knowledge).
  - Upserts using `idempotency_key`.
  - Advances and persists `source_cursor` transactionally.
  - Logs to `ingest_audit`.

Dependencies
- Tasks 01–03.

Implementation Notes
- Store cursor as an ISO date or knowledge integer depending on client support.
- Protect against clock skew: subtract 1 day from since_date.
- Ensure resilience: if run fails, cursor should not advance.

Acceptance Criteria
- Running twice in a row produces no new rows.
- Cursor advances only when ingestion succeeds.
- `ingest_audit` captures timing/rows/status.

Test Guidance
- Mock two delta windows with overlap; assert no duplicates and correct cursor behavior.

Affected/Added Files
- New: `ingest/ynab_delta.py`
- Touch: `cli/budgetctl.py` to wire subcommand.

