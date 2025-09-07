from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, List
from datetime import datetime


def _ensure_schema_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            filename TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )


def _applied(conn: sqlite3.Connection) -> set[str]:
    cur = conn.execute("SELECT filename FROM schema_migrations")
    return {row[0] for row in cur.fetchall()}


def _discover_migrations(migrations_dir: Path) -> List[Path]:
    if not migrations_dir.exists():
        return []
    return sorted(p for p in migrations_dir.iterdir() if p.suffix == ".sql")


def run_migrations(db_path: Path, migrations_dir: Path | None = None) -> List[str]:
    """Run pending SQL migrations idempotently.

    Returns a list of applied filenames.
    """
    migrations_dir = migrations_dir or Path("db/migrations")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    try:
        _ensure_schema_table(conn)
        already = _applied(conn)
        applied: List[str] = []

        for sql_file in _discover_migrations(migrations_dir):
            fname = sql_file.name
            if fname in already:
                continue

            sql = sql_file.read_text(encoding="utf-8")
            # executescript handles multiple statements
            with conn:
                conn.executescript(sql)
                conn.execute(
                    "INSERT INTO schema_migrations(filename, applied_at) VALUES(?, ?)",
                    (fname, datetime.utcnow().isoformat(timespec="seconds") + "Z"),
                )
            applied.append(fname)

        return applied
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run DB migrations")
    parser.add_argument(
        "--db",
        dest="db",
        type=Path,
        default=Path("localdb/budget.db"),
        help="Path to SQLite database file",
    )
    parser.add_argument(
        "--dir",
        dest="migrations_dir",
        type=Path,
        default=Path("db/migrations"),
        help="Path to migrations directory",
    )
    args = parser.parse_args()

    applied = run_migrations(db_path=args.db, migrations_dir=args.migrations_dir)
    if applied:
        print("Applied migrations:", ", ".join(applied))
    else:
        print("No pending migrations.")

