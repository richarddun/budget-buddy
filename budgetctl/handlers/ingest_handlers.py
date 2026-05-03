from __future__ import annotations

from pathlib import Path

from db.migrate import run_migrations
from ingest.csv_importer import run_import as run_csv_import


def ingest_from_csv(db_path: Path, csv_path: Path, account_override: str | None = None) -> int:
    if not csv_path.exists():
        print(f"CSV not found: {csv_path}")
        return 2

    # Ensure schema is applied
    run_migrations(db_path)

    print(f"[ingest:csv] Importing from {csv_path}…")
    try:
        result = run_csv_import(db_path, csv_path, account_override=account_override)
        print(f"[success] Upserted {result.rows_upserted} rows from CSV.")
        return 0 if result.status == "success" else 1
    except Exception as e:
        print(f"[error] CSV import failed: {e}")
        return 1
