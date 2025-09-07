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


def test_binary_search_helper():
    # Import the helper directly
    from api.forecast import _binary_search_max_spend

    # Monotonic predicate: safe if x <= 37
    def is_safe(x: int) -> bool:
        return x <= 37

    assert _binary_search_max_spend(is_safe, 0, 100) == 37
    assert _binary_search_max_spend(is_safe, 0, 37) == 37
    assert _binary_search_max_spend(is_safe, 0, 0) == 0


def test_api_simulate_spend(tmp_path, monkeypatch):
    db_path = tmp_path / "budget_test_api.db"
    _init_test_db(db_path)

    # Seed opening balance via cleared transactions BEFORE start (2025-01-01)
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        # Net opening balance 5000 cents as in other tests
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

        # Seed calendar data to reproduce baseline min 4930 on 2025-01-05
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

    # Point API to this DB
    monkeypatch.setenv("BUDGET_DB_PATH", str(db_path))

    app = load_app()
    client = TestClient(app)

    # Buffer floor just below baseline min (4930), margin = 30
    payload = {
        "date": "2025-01-01",
        "amount_cents": 25,
        "buffer_floor": 4900,
        "mode": "deterministic",
        "horizon_days": 14,
    }
    resp = client.post("/api/forecast/simulate-spend", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    decision = data["decision"]
    # With 25 spend, new min = 4930 - 25 = 4905 >= 4900 → safe
    assert decision["safe"] is True
    assert decision["new_min_balance_cents"] == 4905
    assert decision["max_safe_today_cents"] == 30  # margin to floor

    # Try unsafe amount 31
    payload["amount_cents"] = 31
    resp2 = client.post("/api/forecast/simulate-spend", json=payload)
    assert resp2.status_code == 200
    d2 = resp2.json()["decision"]
    assert d2["safe"] is False
    assert d2["new_min_balance_cents"] == 4930 - 31
    assert d2["max_safe_today_cents"] == 30

