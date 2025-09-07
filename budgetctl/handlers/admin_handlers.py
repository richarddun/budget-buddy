from __future__ import annotations

import sqlite3
from pathlib import Path

from db.migrate import run_migrations
from categories.sync_ynab import run_sync as run_categories_sync


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def sync_categories(db_path: Path) -> int:
    try:
        # Ensure schema is applied
        run_migrations(db_path)
        print("[categories] Syncing categories from YNAB…")
        result = run_categories_sync(db_path)
        print(
            "[success] Groups: {g}, Categories: {c}, Upserts: {u}, Maps touched: {m}".format(
                g=result.ynab_groups_seen,
                c=result.ynab_categories_seen,
                u=result.categories_upserted,
                m=result.maps_created,
            )
        )
        return 0
    except Exception as e:
        print(f"[error] Category sync failed: {e}")
        return 1


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
