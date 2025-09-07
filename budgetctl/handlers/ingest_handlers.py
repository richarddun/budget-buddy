from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from db.migrate import run_migrations
from ingest.ynab_backfill import run_backfill


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _read_source_cursor(conn: sqlite3.Connection, source: str) -> str | None:
    cur = conn.execute("SELECT last_cursor FROM source_cursor WHERE source = ?", (source,))
    row = cur.fetchone()
    return row[0] if row and row[0] else None


def delta_sync(db_path: Path) -> int:
    """Stub delta sync for YNAB.

    - Verifies required env vars exist (without printing secrets)
    - Reads current cursor from DB to prove connectivity
    - Prints actionable message and exits 0
    """
    ynab_token = os.getenv("YNAB_TOKEN")
    budget_id = os.getenv("YNAB_BUDGET_ID")
    if not ynab_token or not budget_id:
        print("YNAB credentials not configured (set YNAB_TOKEN and YNAB_BUDGET_ID).")
        return 2

    with _connect(db_path) as conn:
        cursor = _read_source_cursor(conn, source="ynab")
    print("[ingest:ynab:delta] Starting delta sync…")
    print(f"[db] source_cursor.ynab last_cursor = {cursor!r}")
    print("[noop] No records changed (skeleton mode).")
    return 0


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


def ingest_from_csv(db_path: Path, csv_path: Path) -> int:
    if not csv_path.exists():
        print(f"CSV not found: {csv_path}")
        return 2
    with _connect(db_path) as conn:
        cursor = _read_source_cursor(conn, source="ynab-csv")
    print(f"[ingest:ynab:csv] Importing from {csv_path}…")
    print(f"[db] source_cursor.ynab-csv last_cursor = {cursor!r}")
    print("[noop] Parsed 0 rows (skeleton mode).")
    return 0
