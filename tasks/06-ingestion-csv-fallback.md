Title: Ingestion – CSV Fallback Importer

Context
- Support environments without API access by importing YNAB-exported CSV.

Objective
- Implement `budgetctl ingest ynab --from-csv PATH` to parse and upsert transactions.

Deliverables
- CSV parser that:
  - Maps CSV columns to local schema (date, payee, memo, amount, account, category).
  - Builds a deterministic `idempotency_key` (e.g., hash of row + account name + date).
  - Resolves categories via `category_map` if possible; else holding category.
  - Writes `ingest_audit` row.

Dependencies
- Tasks 01–05.

Implementation Notes
- Normalize dates to ISO day; amounts to integer cents (beware signs).
- Allow `--account` override to route to a specific local account.

Acceptance Criteria
- Re-importing same CSV produces no duplicates.
- Mixed-case/payee/whitespace variations are handled consistently.

Test Guidance
- Fixture CSV with 10 rows, run twice; assert final row count equals 10.

Affected/Added Files
- New: `ingest/csv_importer.py`
- Touch: `cli/budgetctl.py` to wire subcommand.

