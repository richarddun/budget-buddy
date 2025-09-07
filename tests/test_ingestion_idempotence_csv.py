from __future__ import annotations

import sqlite3
from pathlib import Path

from ingest.csv_importer import run_import as csv_run_import


def _count_transactions(dbp: Path) -> int:
    conn = sqlite3.connect(dbp)
    try:
        cur = conn.execute("SELECT COUNT(*) FROM transactions")
        return int(cur.fetchone()[0])
    finally:
        conn.close()


def test_csv_ingestion_idempotence(tmp_path):
    # Prepare temp DB and CSV
    db_path = tmp_path / "idempotence.db"
    csv_path = tmp_path / "sample.csv"

    # Minimal CSV with a single row
    csv_path.write_text(
        "date,payee,memo,amount,category,account,cleared\n"
        "2025-01-02,Coffee Shop,Morning latte,-3.50,Food & Dining,Checking,Cleared\n",
        encoding="utf-8",
    )

    # First import
    r1 = csv_run_import(db_path, csv_path)
    assert r1.status == "success"
    assert _count_transactions(db_path) == 1

    # Second import of the same file should not duplicate
    r2 = csv_run_import(db_path, csv_path)
    assert r2.status == "success"
    assert _count_transactions(db_path) == 1

