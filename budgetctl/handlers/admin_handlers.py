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


def db_reset(
    db_path: Path,
    *,
    populate: bool = True,
    delta: bool = False,
    months: int = 1,
    force: bool = False,
) -> int:
    """Destructively reset the DB file, re-create schema, and optionally repopulate.

    - If the DB file exists, it is deleted. Requires `force=True` to proceed.
    - Runs migrations to re-create schema.
    - If `populate` is True, performs category sync from YNAB, then either
      delta sync (`delta=True`) or backfill (`months` horizon).
    """
    try:
        if db_path.exists():
            if not force:
                print(
                    f"[abort] DB exists at {db_path}. Re-run with --force to delete and reset."
                )
                return 3
            try:
                db_path.unlink()
                print(f"[reset] Deleted existing DB: {db_path}")
            except Exception as e:
                print(f"[error] Failed deleting DB {db_path}: {e}")
                return 1

        # Recreate schema
        applied = run_migrations(db_path)
        print(
            "[reset] Schema initialized. "
            + (f"Applied: {', '.join(applied)}" if applied else "No pending migrations.")
        )

        if not populate:
            print("[reset] Skipping populate as requested (--no-populate).")
            return 0

        # Category sync (requires YNAB credentials)
        try:
            print("[reset] Syncing categories (YNAB)…")
            cat_res = run_categories_sync(db_path)
            print(
                "[reset] Categories OK. Groups: {g}, Categories: {c}, Upserts: {u}, Maps: {m}".format(
                    g=cat_res.ynab_groups_seen,
                    c=cat_res.ynab_categories_seen,
                    u=cat_res.categories_upserted,
                    m=cat_res.maps_created,
                )
            )
        except Exception as e:
            print(f"[error] Category sync failed during reset: {e}")
            return 1

        # Ingest transactions
        try:
            from . import ingest_handlers as _ing

            if delta:
                print("[reset] Running delta transaction sync…")
                rc = _ing.delta_sync(db_path)
                return rc
            else:
                print(f"[reset] Running backfill for last {months} month(s)…")
                rc = _ing.backfill(db_path, months=months)
                return rc
        except Exception as e:
            print(f"[error] Ingestion during reset failed: {e}")
            return 1
    except Exception as e:
        print(f"[error] Reset failed: {e}")
        return 1
