from __future__ import annotations

import importlib
import os
import sqlite3
import sys
from pathlib import Path

from fastapi.testclient import TestClient


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def load_app():
    if 'main' in sys.modules:
        importlib.reload(sys.modules['main'])
    else:
        import main  # noqa: F401
    return sys.modules['main'].app


def _init_test_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        cur = conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS accounts (
              id INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              type TEXT NOT NULL,
              currency TEXT NOT NULL,
              is_active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS categories (
              id INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              parent_id INTEGER,
              is_archived INTEGER NOT NULL DEFAULT 0,
              source TEXT,
              external_id TEXT
            );
            CREATE TABLE IF NOT EXISTS transactions (
              idempotency_key TEXT NOT NULL,
              account_id INTEGER NOT NULL,
              posted_at TEXT NOT NULL,
              amount_cents INTEGER NOT NULL,
              payee TEXT,
              memo TEXT,
              external_id TEXT,
              source TEXT NOT NULL,
              category_id INTEGER,
              is_cleared INTEGER NOT NULL DEFAULT 0,
              import_meta_json TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS uq_transactions_idem_key
              ON transactions(idempotency_key);
            CREATE TABLE IF NOT EXISTS commitments (
              id INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              amount_cents INTEGER NOT NULL,
              due_rule TEXT NOT NULL,
              next_due_date TEXT,
              priority INTEGER,
              account_id INTEGER NOT NULL,
              flexible_window_days INTEGER,
              category_id INTEGER,
              type TEXT NOT NULL
            );
            """
        )
        # Seed basic data for pack assembly
        cur.execute(
            "INSERT INTO accounts(id, name, type, currency, is_active) VALUES (?,?,?,?,?)",
            (1, "Checking", "depository", "USD", 1),
        )
        cur.execute(
            "INSERT INTO commitments(name, amount_cents, due_rule, next_due_date, priority, account_id, flexible_window_days, category_id, type) VALUES (?,?,?,?,?,?,?,?,?)",
            ("Rent", 120000, "MONTHLY", "2025-01-01", 1, 1, 0, None, "bill"),
        )
        # Some income and expense within a simple window
        txs = [
            ("x1", 1, "2025-01-05T00:00:00Z", 50000, "seed", None),
            ("x2", 1, "2025-01-06T00:00:00Z", -2000, "seed", None),
        ]
        for idem, acct, ts, amt, src, cat in txs:
            cur.execute(
                "INSERT INTO transactions(idempotency_key, account_id, posted_at, amount_cents, source, category_id, is_cleared) VALUES (?,?,?,?,?,?,1)",
                (idem, acct, ts, amt, src, cat),
            )
        conn.commit()
    finally:
        conn.close()


def test_hash_stability():
    from api.q_export import compute_export_hash

    sample = {"a": 1, "b": [3, 2, 1], "c": {"x": "y"}}
    ts = "2025-01-01T00:00:00+00:00"
    h1 = compute_export_hash(sample, ts)
    h2 = compute_export_hash({"c": {"x": "y"}, "b": [3, 2, 1], "a": 1}, ts)  # different key order
    assert h1 == h2


def test_export_endpoint_generates_files(tmp_path, monkeypatch):
    db_path = tmp_path / "budget_export.db"
    _init_test_db(db_path)
    monkeypatch.setenv("BUDGET_DB_PATH", str(db_path))

    app = load_app()
    client = TestClient(app)

    # CSV export first
    r = client.post(
        "/api/q/export",
        json={"pack": "affordability_snapshot", "period": "3m_full", "format": "csv"},
    )
    assert r.status_code == 200
    data = r.json()
    assert "csv_url" in data and data["csv_url"].startswith("/exports/")
    # File exists and contains hash string
    csv_path = Path("localdb/exports") / Path(data["csv_url"]).name
    assert csv_path.exists()
    content = csv_path.read_text(encoding="utf-8")
    assert data["hash"] in content

    # PDF (HTML) export
    r2 = client.post(
        "/api/q/export",
        json={"pack": "affordability_snapshot", "period": "3m_full", "format": "pdf"},
    )
    assert r2.status_code == 200
    data2 = r2.json()
    assert "pdf_url" in data2 and data2["pdf_url"].startswith("/exports/")
    html_path = Path("localdb/exports") / Path(data2["pdf_url"]).name
    assert html_path.exists()
    html = html_path.read_text(encoding="utf-8")
    assert data2["hash"] in html

