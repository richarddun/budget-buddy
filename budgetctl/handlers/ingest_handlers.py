from __future__ import annotations

import os
from pathlib import Path

from db.migrate import run_migrations
from ingest.ynab_backfill import run_backfill
from ingest.ynab_delta import run_delta
from ingest.csv_importer import run_import as run_csv_import


def delta_sync(db_path: Path) -> int:
    """Run YNAB delta sync and report results."""
    ynab_token = os.getenv("YNAB_TOKEN")
    budget_id = os.getenv("YNAB_BUDGET_ID")
    if not ynab_token or not budget_id:
        print("YNAB credentials not configured (set YNAB_TOKEN and YNAB_BUDGET_ID).")
        return 2

    # Ensure schema is applied
    run_migrations(db_path)

    print("[ingest:ynab:delta] Starting delta sync…")
    try:
        result = run_delta(db_path)
        print(
            f"[success] Upserted {result.rows_upserted} rows. Mode=delta."
        )
        return 0 if result.status == "success" else 1
    except Exception as e:
        print(f"[error] Delta sync failed: {e}")
        return 1


def backfill(db_path: Path, months: int = 1) -> int:
    ynab_token = os.getenv("YNAB_TOKEN")
    budget_id = os.getenv("YNAB_BUDGET_ID")
    if not ynab_token or not budget_id:
        print("YNAB credentials not configured (set YNAB_TOKEN and YNAB_BUDGET_ID).")
        return 2

    # Ensure schema is applied
    run_migrations(db_path)

    print(f"[ingest:ynab:backfill] Backfilling last {months} month(s)…")
    try:
        result = run_backfill(db_path, months=months)
        print(
            f"[success] Upserted {result.rows_upserted} rows. Window: {months} month(s)."
        )
        return 0 if result.status == "success" else 1
    except Exception as e:
        print(f"[error] Backfill failed: {e}")
        return 1


def ingest_from_csv(db_path: Path, csv_path: Path, account_override: str | None = None) -> int:
    if not csv_path.exists():
        print(f"CSV not found: {csv_path}")
        return 2

    # Ensure schema is applied
    run_migrations(db_path)

    print(f"[ingest:ynab:csv] Importing from {csv_path}…")
    try:
        result = run_csv_import(db_path, csv_path, account_override=account_override)
        print(f"[success] Upserted {result.rows_upserted} rows from CSV.")
        return 0 if result.status == "success" else 1
    except Exception as e:
        print(f"[error] CSV import failed: {e}")
        return 1
