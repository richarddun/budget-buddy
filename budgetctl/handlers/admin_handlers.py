from __future__ import annotations

import sqlite3
from pathlib import Path

from db.migrate import run_migrations


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def sync_categories(db_path: Path) -> int:
    with _connect(db_path) as conn:
        # Touch the categories table to prove DB connectivity
        conn.execute(
            "CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"
        )
    print("[categories] Sync from YNAB (skeleton)…")
    print("[noop] Categories snapshot not implemented in skeleton.")
    return 0


def reconcile(db_path: Path) -> int:
    with _connect(db_path) as conn:
        # Demonstrate a quick check — count transactions if table exists
        try:
            cur = conn.execute("SELECT COUNT(1) FROM transactions")
            count = cur.fetchone()[0]
        except sqlite3.OperationalError:
            count = 0
    print("[reconcile] Running reconciliation checks (skeleton)…")
    print(f"[db] transactions count = {count}")
    print("[noop] No issues detected in skeleton mode.")
    return 0


def db_migrate(db_path: Path) -> int:
    applied = run_migrations(db_path)
    if applied:
        print("Applied migrations:", ", ".join(applied))
    else:
        print("No pending migrations.")
    return 0

