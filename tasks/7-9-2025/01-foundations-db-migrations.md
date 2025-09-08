Title: Foundations – Database Migrations and Core Schema

Context
- This codebase currently ingests YNAB data and renders UI via FastAPI.
- The spec introduces a local source-of-truth data model decoupled from YNAB.
- Use integer cents for currency; ISO dates (UTC day) for timestamps.

Objective
- Create initial DB migrations/tables to support local SoT and upcoming features.

Deliverables
- Migration or bootstrap DDL that creates the following tables:
  - accounts(id, name, type, currency, is_active)
  - transactions(idempotency_key, account_id, posted_at, amount_cents, payee, memo, external_id, source, category_id NULL, is_cleared, import_meta_json)
  - categories(id, name, parent_id NULL, is_archived, source, external_id NULL)
  - category_map(source, external_id, internal_category_id)
  - commitments(id, name, amount_cents, due_rule, next_due_date, priority INT, account_id, flexible_window_days INT, category_id, type)
  - scheduled_inflows(id, name, amount_cents, due_rule, next_due_date, account_id, type)
  - key_spend_events(id, name, event_date, repeat_rule NULL, planned_amount_cents, category_id, lead_time_days INT, shift_policy, account_id)
  - forecast_snapshot(id, created_at, horizon_start, horizon_end, json_payload, min_balance_cents, min_balance_date)
  - source_cursor(source, last_cursor, updated_at)
  - ingest_audit(id, source, run_started_at, run_finished_at, rows_upserted, status, notes)
  - question_category_alias(id, alias, category_id)

Dependencies
- None. This is the first step. Prefer SQLite first; keep SQL portable for Postgres later.

Implementation Notes
- Introduce a lightweight migration mechanism (e.g., simple versioned SQL files under `db/migrations/` and a tiny runner in `main.py` or a `budgetctl db migrate`).
- For SQLite types, use INTEGER, TEXT, and store JSON as TEXT.
- Add unique constraints:
  - transactions.idempotency_key unique
  - category_map(source, external_id) unique
  - source_cursor.source unique
- Add indexes on transactions(posted_at), transactions(account_id), forecast_snapshot(created_at).
- Keep DDL idempotent for local bootstrapping in dev.

Acceptance Criteria
- Fresh database initializes cleanly with all tables.
- Re-running migration is a no-op (idempotent guard).
- Schema matches names/types above; integer cents only.

Test Guidance
- Unit test: open SQLite in memory, run migration, assert tables/indices exist.
- Insert a sample transaction with idempotency_key, assert unique constraint enforced.

Affected/Added Files
- New: `db/migrations/0001_init.sql` (and optional `db/migrate.py` if needed)
- Touch: `main.py` or `budgetctl` to ensure migrations run on startup/command.

