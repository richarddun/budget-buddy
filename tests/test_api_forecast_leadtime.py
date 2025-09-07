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
            CREATE TABLE IF NOT EXISTS scheduled_inflows (
              id INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              amount_cents INTEGER NOT NULL,
              due_rule TEXT NOT NULL,
              next_due_date TEXT,
              account_id INTEGER NOT NULL,
              type TEXT NOT NULL
            );
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
            CREATE TABLE IF NOT EXISTS key_spend_events (
              id INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              event_date TEXT NOT NULL,
              repeat_rule TEXT,
              planned_amount_cents INTEGER,
              category_id INTEGER,
              lead_time_days INTEGER,
              shift_policy TEXT,
              account_id INTEGER
            );
            """
        )
        cur.execute(
            "INSERT INTO accounts(id, name, type, currency, is_active) VALUES (?,?,?,?,?)",
            (1, "Checking", "depository", "USD", 1),
        )
        conn.commit()
    finally:
        conn.close()


def test_lead_window_boundaries(tmp_path, monkeypatch):
    db_path = tmp_path / "budget_leadtime.db"
    _init_test_db(db_path)

    # Seed two key events: one exactly at boundary, one just outside
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        # No need for transactions for this test; opening balance defaults to 0
        # Lead window = 5 days
        cur.execute(
            "INSERT INTO key_spend_events(name, event_date, repeat_rule, planned_amount_cents, lead_time_days, shift_policy, account_id) VALUES (?,?,?,?,?,?,?)",
            ("Birthday Alice", "2025-01-06", "ONE_OFF", 1000, 5, "AS_SCHEDULED", 1),
        )
        cur.execute(
            "INSERT INTO key_spend_events(name, event_date, repeat_rule, planned_amount_cents, lead_time_days, shift_policy, account_id) VALUES (?,?,?,?,?,?,?)",
            ("Holiday Trip", "2025-01-07", "ONE_OFF", 2000, 5, "AS_SCHEDULED", 1),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setenv("BUDGET_DB_PATH", str(db_path))

    app = load_app()
    client = TestClient(app)

    # Treat start as "today" for lead-window logic (per API implementation)
    resp = client.get(
        "/api/forecast/calendar",
        params={"start": "2025-01-01", "end": "2025-01-10"},
    )
    assert resp.status_code == 200
    data = resp.json()

    kv = { (e["name"], e["date"]): e for e in data.get("entries", []) if e["type"] == "key_event" }
    assert kv[("Birthday Alice", "2025-01-06")]["is_within_lead_window"] is True
    assert kv[("Holiday Trip", "2025-01-07")]["is_within_lead_window"] in (False, None)

    # UI marker present for key events
    assert kv[("Birthday Alice", "2025-01-06")]["ui_marker"] in ("🎂", "🎯", "🎄")

