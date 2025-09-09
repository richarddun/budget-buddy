# Ops Runbook – Forecast Debug + Ledger Export

This runbook documents the operator endpoints added for inspecting what drives the runway graph on any date.

- Base path: respect `config.BASE_PATH` (e.g., `/budget-buddy`).
- Auth: when `ADMIN_TOKEN` is set, include `X-Admin-Token: $ADMIN_TOKEN` on protected routes.
- CSRF: not required for these GET endpoints.

## List Accounts (helper)

- `GET {BASE}/api/accounts`
- Use to discover account IDs for filtering (e.g., `1` for `CURRENT-166`).

Example

- `curl -s "https://your.host{BASE}/api/accounts" | jq`

### Optional: Per-account overdraft alert thresholds

Configure env `OVERDRAFT_ALERT_THRESHOLDS` to drive a UI alert when the projected balance dips below a floor.

- Format: `OVERDRAFT_ALERT_THRESHOLDS="<account_id>:<threshold_cents>,..."`
- Example for account 1 with −€775.00 alert level: `OVERDRAFT_ALERT_THRESHOLDS="1:-77500"`
- Inspect via API: `GET {BASE}/api/accounts/floors`

## Forecast Calendar Debug

Explain the deterministic forecast day-by-day for a horizon.

- `GET {BASE}/api/forecast/calendar/debug?start=YYYY-MM-DD&end=YYYY-MM-DD[&accounts=1,2]`
- Auth: optional; enforced only if `ADMIN_TOKEN` is configured.
- Response fields:
  - `opening_balance_cents`: sum of cleared transactions across the selected accounts as of `start - 1`.
  - `entries[]`: expanded calendar items in window (inflows, commitments, key events) with shift flags.
  - `rows[]`: for each date in `[start, end]` — `opening_balance_cents`, `delta_cents` (sum of entries that day), `closing_balance_cents`, and contributing `items`.

Examples

- Local/dev:
  - `curl -s "http://localhost:8000{BASE}/api/forecast/calendar/debug?start=2025-08-01&end=2025-08-31&accounts=1" | jq '.rows[] | select(.date=="2025-08-25")'`
- Production with admin token:
  - `curl -s -H "X-Admin-Token: $ADMIN_TOKEN" "https://your.host{BASE}/api/forecast/calendar/debug?start=2025-08-01&end=2025-08-31&accounts=1" | jq '.rows[0], .rows[-1]'`

Notes

- The opening balance honors the `accounts` filter. If the chart is filtered to a single account, pass the same `accounts` set here.
- Key-event amount convention: positive = expense (subtract), negative = income (add).

## Transactions Export (ledger)

Export transactions in a date window for cross-checking the opening balance and deltas.

- `GET {BASE}/api/transactions/export?from=YYYY-MM-DD&end=YYYY-MM-DD[&accounts=1,2][&include_uncleared=false][&limit=5000][&offset=0]`
- Auth: requires `X-Admin-Token` when `ADMIN_TOKEN` is set.
- Response: `transactions[]` with `posted_at`, `amount_cents`, `account_name`, `category_name`, `is_cleared`, `source`, etc.

Examples

- Sum transactions to compute opening as of a date:
  - `curl -s -H "X-Admin-Token: $ADMIN_TOKEN" "https://your.host{BASE}/api/transactions/export?from=1970-01-01&end=2025-08-24&accounts=1" \
    | jq '[.transactions[].amount_cents] | add'`
- Inspect window around a cliff date:
  - `curl -s -H "X-Admin-Token: $ADMIN_TOKEN" "https://your.host{BASE}/api/transactions/export?from=2025-08-20&end=2025-08-26&accounts=1" | jq`

## Anchors (per-account)

Define a ground-truth balance and optional overdraft floor for an account.

- Schema: `account_anchors(account_id PK, anchor_date TEXT, anchor_balance_cents INT, min_floor_cents INT NULL)`
- List: `GET {BASE}/api/accounts/anchors`
- Upsert: `PUT {BASE}/api/accounts/{id}/anchor` (admin + CSRF)
  - Body: `{ "anchor_date": "YYYY-MM-DD", "anchor_balance_cents": 200000, "min_floor_cents": -75000 }`

Forecast behavior with anchors
- Opening(as_of, accounts=S) = Σ over accounts of:
  - If `as_of >= anchor_date`: `anchor_balance + sum(cleared (anchor_date+1 .. as_of])`
  - If `as_of < anchor_date`: `anchor_balance - sum(cleared (as_of+1 .. anchor_date])`
- UI alerts prefer `min_floor_cents` from anchors for overdraft reconciliation checks.

Example (account 1)
- `curl -s -X PUT "https://your.host{BASE}/api/accounts/1/anchor" \
   -H "Content-Type: application/json" -H "X-Admin-Token: $ADMIN_TOKEN" -H "X-CSRF-Token: $CSRF_TOKEN" \
   -d '{"anchor_date":"2025-09-10","anchor_balance_cents":200000,"min_floor_cents":-75000}' | jq`

## Quick Workflow to Explain a Date

1) Identify the horizon and account(s).
2) Call Forecast Debug with `accounts` filter.
3) Look at the `rows[]` entry for the date of interest; note opening, delta, closing and `items`.
4) If opening seems off, export ledger up to `start-1` for the same `accounts` and sum `amount_cents` to reconcile.
5) If a calendar item is unexpected, check `entries[]` for its `source_id` and confirm in DB (`commitments`, `scheduled_inflows`, `key_spend_events`).

## Base-URL Tips

- In curl examples, replace `{BASE}` with your configured base path, e.g. `/budget-buddy`.
- When testing locally with a root path of `/`, omit `{BASE}`.
