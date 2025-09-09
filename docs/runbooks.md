# Admin Runbooks

This document provides concise, operator-focused runbooks for common Budget Buddy administration tasks. Commands assume repository root as the working directory.

- Binary: `python -m budgetctl` or `budgetctl` if installed
- Default DB: `localdb/budget.db` (override with `--db PATH`)
- Environment: `.env` should provide `YNAB_TOKEN` and `YNAB_BUDGET_ID`

## Admin Auth & CSRF

Provision admin tokens for write-protected endpoints and UI pages.

- Generate tokens:
  - `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`
- Configure `.env` and restart app:
  - `ADMIN_TOKEN=<generated>`
  - `CSRF_TOKEN=<generated>`
- Client headers used by the app and admin UI:
  - `X-Admin-Token: $ADMIN_TOKEN`
  - `X-CSRF-Token: $CSRF_TOKEN`
- Admin UI page: `GET /admin` — paste your admin token (stored in browser localStorage) and edit anchors/floors.

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

## DB Reset

Destructive reset (purge DB file, re-create schema, and repopulate)
- `python -m budgetctl db reset --force` (default repopulates via categories sync + 1-month backfill)
- Options:
  - `--db PATH` — target DB file (default `localdb/budget.db`)
  - `--no-populate` — skip pulling data (schema only)
  - `--delta` — populate via delta sync instead of backfill
  - `--backfill --months N` — populate via backfill (default N=1)

Notes
- Requires `YNAB_TOKEN` and `YNAB_BUDGET_ID` when populate is enabled.
- Use `--force` to bypass the safety check when deleting an existing DB file.

## Reconcile

Lightweight reconciliation check
- `python -m budgetctl reconcile`
- Current behavior: prints a quick DB sanity status (e.g., transactions count). Extend as needed.

Compare to latest forecast snapshot (manual inspection)
- List the latest snapshot row:
  - `sqlite3 localdb/budget.db "SELECT created_at, horizon_start, horizon_end, min_balance_cents, min_balance_date FROM forecast_snapshot ORDER BY created_at DESC LIMIT 1;"`
- View the overview digest (derived from latest snapshot) via API/UI:
  - Open `/overview` in the running app, or `GET /api/overview`.

### Forecast Debug & Ledger Export (Diagnostics)

Explain what drives the runway and cross‑check the ledger.

- Forecast calendar debug (read‑only):
  - `GET {BASE}/api/forecast/calendar/debug?start=YYYY-MM-DD&end=YYYY-MM-DD[&accounts=1,2]`
  - Returns opening balance as of `start-1`, expanded entries, and day‑by‑day rows with opening → delta → closing breakdown.
- Transactions export (read‑only, admin):
  - `GET {BASE}/api/transactions/export?from=YYYY-MM-DD&end=YYYY-MM-DD[&accounts=1,2][&include_uncleared=false][&limit=5000][&offset=0]`
  - Returns `transactions[]` with account/category names and cleared flags.
- Accounts helper: `GET {BASE}/api/accounts`

Quick example:

```
curl -s "https://your.host{BASE}/api/forecast/calendar/debug?start=2025-08-01&end=2025-08-31&accounts=1" | jq '.rows[] | select(.date=="2025-08-25")'
curl -s -H "X-Admin-Token: $ADMIN_TOKEN" "https://your.host{BASE}/api/transactions/export?from=2025-08-20&end=2025-08-26&accounts=1" | jq '[.transactions[].amount_cents] | add'
```

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

---

# Account Anchors & Overdraft Floors

Anchors provide a ground‑truth balance per account and an optional overdraft reconciliation floor. Forecast openings are derived from anchors + cleared transaction deltas.

Schema
- Table: `account_anchors(account_id PK, anchor_date TEXT, anchor_balance_cents INTEGER, min_floor_cents INTEGER NULL)`
- Migration: applied automatically (`db/migrations/0002_account_anchors.sql`).

APIs
- List anchors: `GET {BASE}/api/accounts/anchors`
- Upsert anchor: `PUT {BASE}/api/accounts/{id}/anchor` (admin + CSRF)
  - Body: `{ "anchor_date": "YYYY-MM-DD", "anchor_balance_cents": 200000, "min_floor_cents": -75000 }`
- Optional env fallback for floors: `OVERDRAFT_ALERT_THRESHOLDS="1:-77500,2:-60000"`
  - Inspect: `GET {BASE}/api/accounts/floors`

Forecast behavior
- With account filter, opening(as_of) per account:
  - If `as_of >= anchor_date`: `anchor_balance + sum(cleared (anchor_date+1 .. as_of])`
  - If `as_of < anchor_date`: `anchor_balance - sum(cleared (as_of+1 .. anchor_date])`
- Without anchors: falls back to sum of cleared ≤ `as_of`.

UI integration
- Admin UI `/admin` lets you edit anchors and floors.
- Budget Health uses `min_floor_cents` (or env mapping) to raise a critical alert when the projection dips below the floor (no clamping).

Example

```
curl -s -X PUT "https://your.host{BASE}/api/accounts/1/anchor" \
  -H "Content-Type: application/json" -H "X-Admin-Token: $ADMIN_TOKEN" -H "X-CSRF-Token: $CSRF_TOKEN" \
  -d '{"anchor_date":"2025-09-10","anchor_balance_cents":200000,"min_floor_cents":-75000}' | jq
```
