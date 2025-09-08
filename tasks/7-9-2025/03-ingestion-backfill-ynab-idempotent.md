Title: Ingestion – Idempotent YNAB Backfill (`--months N`) with Audit

Context
- Use YNAB only as a read-only source (API).
- Import into local SoT tables with idempotent upserts and audit logging.

Objective
- Implement `budgetctl ingest ynab --backfill --months N` to fetch historical transactions and upsert locally.

Deliverables
- Backfill function that:
  - Pages/fetches last N months from YNAB.
  - Builds an `idempotency_key` (e.g., `source:ynab:{account_id}:{external_id}`) per transaction.
  - Upserts into `transactions` using the key; maintains `accounts` as needed.
  - Writes a row in `ingest_audit` with counts, timing, and status.

Dependencies
- Task 01 (DB schema) and Task 02 (CLI).

Implementation Notes
- Place logic in `ingest/ynab_backfill.py` and call from CLI.
- Derive categories via `category_map` if already present, else leave NULL.
- Use `source_cursor` minimally or leave empty (cursor is for delta sync).
- Robust error handling; partial upserts are OK as long as idempotency is respected.

Acceptance Criteria
- Re-running backfill for same window does not create duplicates.
- `ingest_audit` row reflects rows upserted and status=success.
- Accounts are created/updated as encountered.

Test Guidance
- Mock YNAB client and feed a deterministic set for 2 months; run twice; assert transaction count unchanged on second run.

Affected/Added Files
- New: `ingest/ynab_backfill.py`
- Touch: `cli/budgetctl.py` to wire subcommand.

