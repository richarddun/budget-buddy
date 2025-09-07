# Admin Runbooks

This document provides concise, operator-focused runbooks for common Budget Buddy administration tasks. Commands assume repository root as the working directory.

- Binary: `python -m budgetctl` or `budgetctl` if installed
- Default DB: `localdb/budget.db` (override with `--db PATH`)
- Environment: `.env` should provide `YNAB_TOKEN` and `YNAB_BUDGET_ID`

## Ingestion

Prerequisites
- `YNAB_TOKEN` and `YNAB_BUDGET_ID` are set in environment or `.env`.
- Schema migrations are applied automatically by commands below.

Backfill (last N months)
- `python -m budgetctl ingest ynab --backfill --months 3`
- Writes idempotent upserts to `accounts` and `transactions`.
- Records run details in `ingest_audit`.

Delta sync (since last cursor)
- `python -m budgetctl ingest ynab --delta`
- Uses `source_cursor(source='ynab')` with 1-day overlap handling.
- Records run details in `ingest_audit` and advances cursor on success.

CSV import (fallback)
- `python -m budgetctl ingest ynab --from-csv /path/to/ynab.csv [--account "Account Name"]`
- Parses YNAB CSV exports and upserts deterministically.
- Records run details in `ingest_audit`.

## Categories

Snapshot YNAB categories and refresh `category_map`
- `python -m budgetctl categories sync-ynab`
- Behavior:
  - Upserts YNAB groups/categories into `categories` with `source='ynab'`.
  - For mapping, prefers existing `category_map` entries.
  - Otherwise attempts name match to internal categories.
  - Otherwise maps to the internal `Holding` category (auto-created if missing).
- Output includes counts for groups, categories, upserts, and maps touched.

## Reconcile

Lightweight reconciliation check
- `python -m budgetctl reconcile`
- Current behavior: prints a quick DB sanity status (e.g., transactions count). Extend as needed.

Compare to latest forecast snapshot (manual inspection)
- List the latest snapshot row:
  - `sqlite3 localdb/budget.db "SELECT created_at, horizon_start, horizon_end, min_balance_cents, min_balance_date FROM forecast_snapshot ORDER BY created_at DESC LIMIT 1;"`
- View the overview digest (derived from latest snapshot) via API/UI:
  - Open `/overview` in the running app, or `GET /api/overview`.

## Exports (Questionnaire Packs)

Endpoint: `POST /api/q/export` (requires admin auth + CSRF)
- Env vars required: `ADMIN_TOKEN`, `CSRF_TOKEN`
- Optional: `EXPORT_DIR` (default `localdb/exports`)
- Formats: `csv | pdf | both`
- Packs: `loan_application_basics`, `affordability_snapshot`

Example (CSV only)
- `curl -s -X POST http://localhost:8000/api/q/export -H "Content-Type: application/json" -H "X-Admin-Token: $ADMIN_TOKEN" -H "X-CSRF-Token: $CSRF_TOKEN" -d '{"pack":"loan_application_basics","period":"3m_full","format":"csv"}' | jq`
- Response fields: `hash`, `generated_at`, `csv_url`.
- File is written under `$EXPORT_DIR` and served under `/exports/`.

Example (PDF HTML and CSV)
- `curl -s -X POST http://localhost:8000/api/q/export -H "Content-Type: application/json" -H "X-Admin-Token: $ADMIN_TOKEN" -H "X-CSRF-Token: $CSRF_TOKEN" -d '{"pack":"affordability_snapshot","period":"3m_full","format":"both"}' | jq`

Integrity verification
- The API returns a `hash` and embeds the same hash in the CSV/PDF HTML footer.
- To audit later, confirm the embedded file hash matches the recorded value.
- To independently recompute the hash, reproduce the export payload and apply the same algorithm: stable JSON of the redacted pack plus the generation timestamp (see `api/q_export.py:compute_export_hash`).

## Notes

- The FastAPI app statically serves exports from `/exports` and receipts from `/receipts`.
- Configure `BUFFER_FLOOR_CENTS` to influence safe-to-spend calculations in digests.
- The daily ingestion scheduler can be enabled via `.env` (see repository README).
