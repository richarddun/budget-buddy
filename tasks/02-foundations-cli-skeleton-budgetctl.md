Title: Foundations – CLI Skeleton `budgetctl`

Context
- We need consistent entry points for ingestion, category mapping, and reconcile ops.
- CLI will be used by cron/systemd and by developers locally.

Objective
- Add a small Python CLI (`budgetctl`) with subcommands for ingest and admin tasks.

Deliverables
- CLI with the following commands (argument parsing + stubs):
  - `budgetctl ingest ynab --delta`
  - `budgetctl ingest ynab --backfill --months N`
  - `budgetctl ingest ynab --from-csv PATH`
  - `budgetctl categories sync-ynab`
  - `budgetctl reconcile`
  - (optional) `budgetctl db migrate`

Dependencies
- Task 01 (DB schema) to store ingest cursors and audit.

Implementation Notes
- Implement with `argparse` or `typer`.
- Wire stubs to minimal functions living in modules where real logic will land (e.g., `ingest/ynab.py`, `ingest/csv.py`, `admin/reconcile.py`).
- Return proper exit codes, log to stdout.
- Respect env vars for tokens but avoid printing secrets.

Acceptance Criteria
- Running each subcommand prints a clear, actionable stub or executes a small no-op that touches the DB where applicable (e.g., read source_cursor).
- CLI is packaged/run via `python -m budgetctl` or a console_script entrypoint.

Test Guidance
- Unit tests: parse args, ensure subcommand dispatch, verify no exceptions.

Affected/Added Files
- New: `cli/budgetctl.py` (or package `budgetctl/__init__.py`, `budgetctl/cli.py`)
- Touch: `requirements.txt` if adding `typer`.

