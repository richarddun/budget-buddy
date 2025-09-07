from __future__ import annotations

import importlib
import os
import sqlite3
import sys
from datetime import date
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


def test_api_forecast_calendar(tmp_path, monkeypatch):
    db_path = tmp_path / "budget_test_api.db"
    _init_test_db(db_path)

    # Seed opening balance via cleared transactions BEFORE start
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        # Two transactions on/before 2025-01-01 that net to +5000 cents
        cur.execute(
            """
            INSERT INTO transactions(idempotency_key, account_id, posted_at, amount_cents, source, is_cleared)
            VALUES (?,?,?,?,?,?)
            """,
            ("idem-1", 1, "2024-12-31T12:00:00Z", 10000, "seed", 1),
        )
        cur.execute(
            """
            INSERT INTO transactions(idempotency_key, account_id, posted_at, amount_cents, source, is_cleared)
            VALUES (?,?,?,?,?,?)
            """,
            ("idem-2", 1, "2025-01-01T08:00:00Z", -5000, "seed", 1),
        )

        # A transaction AFTER start should not count toward opening
        cur.execute(
            """
            INSERT INTO transactions(idempotency_key, account_id, posted_at, amount_cents, source, is_cleared)
            VALUES (?,?,?,?,?,?)
            """,
            ("idem-3", 1, "2025-01-02T00:00:00Z", 99999, "seed", 1),
        )

        # Seed calendar data (same shapes as calendar tests)
        cur.execute(
            """
            INSERT INTO scheduled_inflows(name, amount_cents, due_rule, next_due_date, account_id, type)
            VALUES (?,?,?,?,?,?)
            """,
            ("Payday", 100_00, "WEEKLY", "2025-01-04", 1, "payroll"),
        )
        cur.execute(
            """
            INSERT INTO commitments(name, amount_cents, due_rule, next_due_date, priority, account_id, flexible_window_days, category_id, type)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            ("Rent", 50_00, "MONTHLY", "2025-01-05", 1, 1, 2, None, "bill"),
        )
        cur.execute(
            """
            INSERT INTO key_spend_events(name, event_date, repeat_rule, planned_amount_cents, category_id, lead_time_days, shift_policy, account_id)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            ("Birthday", "2025-01-05", "ONE_OFF", 20_00, None, None, "AS_SCHEDULED", 1),
        )
        conn.commit()
    finally:
        conn.close()

    # Point forecast to this DB
    monkeypatch.setenv("BUDGET_DB_PATH", str(db_path))

    app = load_app()
    client = TestClient(app)

    resp = client.get(
        "/api/forecast/calendar",
        params={"start": "2025-01-01", "end": "2025-01-10", "buffer_floor": 0},
    )
    assert resp.status_code == 200
    data = resp.json()

    # Opening balance is from transactions on/before 2025-01-01: 10000 - 5000 = 5000
    assert data["opening_balance_cents"] == 5000

    # Expect balances for the 3 entry dates, and min balance on 2025-01-05
    balances = data["balances"]
    assert balances["2025-01-03"] == 4950  # 5000 - 50
    assert balances["2025-01-05"] == 4930  # 4950 - 20
    assert balances["2025-01-06"] == 5030  # 4930 + 100

    assert data["min_balance_cents"] == 4930
    assert data["min_balance_date"] == "2025-01-05"

