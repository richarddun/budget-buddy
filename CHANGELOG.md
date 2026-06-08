# Changelog

## 2026-06-07 — CSV Import Fix + Commitments Auto-Generation

### CSV Import — Now Works With AIB Bank Exports

**Problem:** The `/api/csv-import/confirm` endpoint bypassed the bank parser system, calling `run_import()` which only handled YNAB-format CSVs (with `date`, `payee`, `outflow` columns). The parser system (`ingest/parsers/`) had parsers for AIB, PTSB, BOI, Revolut — but they were only used for the preview step, never the actual import.

**Fix:**
- `ingest/parsers/aib_parser.py` — Added "Format B" detection for the actual AIB column names (`Posted Transactions Date`, `Description1`, `Debit Amount`, `Credit Amount`, `Balance`). The parser now handles both the classic AIB 365 format and the newer transaction export format.
- `ingest/csv_importer.py` — New `run_import_from_parsed_rows()` function that accepts parser-normalised canonical rows (from any parser) and upserts them idempotently.
- `api/csv_import.py` — Confirm endpoint now: detects parser → parses all rows through it → calls `run_import_from_parsed_rows()`. If no parser matches, returns a clear error with the CSV headers for debugging.

### Commitments — Auto-Generation from Subscription Detection

**Problem:** The `/subscriptions` endpoint detected 136 recurring payment patterns with confidence scores, but the `commitments` table was empty — nothing bridged detection to actual commitment rows.

**Fix:**
- `main.py` — New `POST /api/commitments/generate-from-subscriptions` endpoint. Calls the subscription detector, filters for confidence ≥ 70%, and creates commitment rows idempotently (matched by payee name). Estimates `next_due_date` from `last_seen + avg_interval_days`.
- `templates/commitments.html` — Added "Generate from Subscriptions" button that calls the endpoint and refreshes the list.

### Git Auto-Deploy Pipeline

- `auto_deploy.sh` on the Pi — Polls `origin/main` every minute. On new commits: `git pull` + restart uvicorn. Logs to `/tmp/budget-buddy-autodeploy.log`.
- Pi now uses a dedicated SSH key (`~/.ssh/id_ed25519_github`) for GitHub authentication.
- Added to crontab: `* * * * * /home/richard/servers/auto_deploy.sh`

### Development Workflow

```
~/projects/budget-buddy/  →  git push origin main  →  Pi auto-pulls within 60s  →  service restarts
```
