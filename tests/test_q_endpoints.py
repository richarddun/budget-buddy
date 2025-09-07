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
            CREATE TABLE IF NOT EXISTS question_category_alias (
              id INTEGER PRIMARY KEY,
              alias TEXT NOT NULL,
              category_id INTEGER NOT NULL
            );
            """
        )
        cur.execute(
            "INSERT INTO accounts(id, name, type, currency, is_active) VALUES (?,?,?,?,?)",
            (1, "Checking", "depository", "USD", 1),
        )
        # Categories: 100=Food, 101=Groceries (child)
        cur.execute("INSERT INTO categories(id, name, parent_id, is_archived) VALUES (?,?,?,?)", (100, "Food", None, 0))
        cur.execute("INSERT INTO categories(id, name, parent_id, is_archived) VALUES (?,?,?,?)", (101, "Groceries", 100, 0))
        # Alias 'groceries' -> 101
        cur.execute("INSERT INTO question_category_alias(alias, category_id) VALUES (?,?)", ("groceries", 101))
        # Transactions in Jan and Feb 2025, groceries expenses and one income
        txns = [
            ("t1", 1, "2025-01-05T10:00:00Z", -1500, "seed", 101),
            ("t2", 1, "2025-01-10T10:00:00Z", -500, "seed", 101),
            ("t3", 1, "2025-02-03T10:00:00Z", -700, "seed", 101),
            ("t_income", 1, "2025-01-15T08:00:00Z", 5000, "seed", None),
            ("t_misc", 1, "2025-01-20T12:00:00Z", -300, "seed", 100),
        ]
        for idem, acct, ts, amt, src, cat in txns:
            cur.execute(
                """
                INSERT INTO transactions(idempotency_key, account_id, posted_at, amount_cents, source, category_id, is_cleared)
                VALUES (?,?,?,?,?,?,1)
                """,
                (idem, acct, ts, amt, src, cat),
            )
        # Commitments: one bill and one loan
        cur.execute(
            """
            INSERT INTO commitments(name, amount_cents, due_rule, next_due_date, priority, account_id, flexible_window_days, category_id, type)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            ("Rent", 120000, "MONTHLY", "2025-01-01", 1, 1, 0, None, "bill"),
        )
        cur.execute(
            """
            INSERT INTO commitments(name, amount_cents, due_rule, next_due_date, priority, account_id, flexible_window_days, category_id, type)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            ("Car Loan", 25000, "MONTHLY", "2025-01-05", 1, 1, 0, None, "loan"),
        )
        conn.commit()
    finally:
        conn.close()


def test_q_endpoints(tmp_path, monkeypatch):
    db_path = tmp_path / "budget_q.db"
    _init_test_db(db_path)

    monkeypatch.setenv("BUDGET_DB_PATH", str(db_path))
    app = load_app()
    client = TestClient(app)

    start = "2025-01-01"
    end_jan = "2025-01-31"
    end_feb = "2025-02-28"

    # monthly total by category (groceries alias) in January
    r = client.get("/api/q/monthly-total-by-category", params={"start": start, "end": end_jan, "category": "groceries"})
    assert r.status_code == 200
    data = r.json()
    # -1500 + -500 = -2000
    assert data["value_cents"] == -2000
    assert set(data["evidence_ids"]) == {"t1", "t2"}
    assert data["method"]

    # monthly average by category across Jan..Feb: total -2700 over 2 months = -1350
    r = client.get("/api/q/monthly-average-by-category", params={"start": start, "end": end_feb, "category": "groceries"})
    assert r.status_code == 200
    avg = r.json()
    assert avg["value_cents"] == -1350
    assert set(avg["evidence_ids"]) >= {"t1", "t2", "t3"}

    # income summary in January
    r = client.get("/api/q/summary/income", params={"start": start, "end": end_jan})
    assert r.status_code == 200
    inc = r.json()
    assert inc["value_cents"] == 5000
    assert "t_income" in set(inc["evidence_ids"]) if inc.get("evidence_ids") else True

    # active loans list contains the car loan
    r = client.get("/api/q/active-loans")
    assert r.status_code == 200
    loans = r.json()
    names = [row["name"] for row in loans.get("rows", [])]
    assert "Car Loan" in names

    # subscriptions returns the rent bill
    r = client.get("/api/q/subscriptions", params={"start": start, "end": end_jan})
    assert r.status_code == 200
    subs = r.json()
    sub_names = [row["name"] for row in subs.get("rows", [])]
    assert "Rent" in sub_names

    # category breakdown includes Groceries and Food (misc)
    r = client.get("/api/q/category-breakdown", params={"start": start, "end": end_jan})
    assert r.status_code == 200
    br = r.json()
    cats = {row["category_name"]: row["total_cents"] for row in br.get("rows", [])}
    assert cats.get("Groceries") == -2000
    assert cats.get("Food") == -300

    # supporting transactions for groceries, Jan window
    r = client.get(
        "/api/q/supporting-transactions",
        params={"start": start, "end": end_jan, "category": "groceries", "page": 1, "page_size": 10},
    )
    assert r.status_code == 200
    supp = r.json()
    keys = [row["idempotency_key"] for row in supp.get("rows", [])]
    assert keys == ["t1", "t2"]
    assert set(supp.get("evidence_ids", [])) == {"t1", "t2"}
    assert supp["pagination"]["total"] == 2

    # household fixed costs are negative and include Rent only in our seed
    r = client.get("/api/q/household-fixed-costs")
    assert r.status_code == 200
    fixed = r.json()
    # Sum of commitments of types bill/rent/mortgage/utility: only Rent 120000
    assert fixed["value_cents"] == -120000
    assert any(e.startswith("commitment:") for e in fixed.get("evidence_ids", []))

