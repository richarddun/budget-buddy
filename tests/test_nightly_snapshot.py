from __future__ import annotations

import os
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from jobs.nightly_snapshot import run_nightly_snapshot


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
            CREATE TABLE IF NOT EXISTS forecast_snapshot (
              id INTEGER PRIMARY KEY,
              created_at TEXT NOT NULL,
              horizon_start TEXT NOT NULL,
              horizon_end TEXT NOT NULL,
              json_payload TEXT NOT NULL,
              min_balance_cents INTEGER,
              min_balance_date TEXT
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


def test_nightly_snapshot_creates_row_and_digest(tmp_path, monkeypatch):
    db_path = tmp_path / "budget_snapshot.db"
    _init_test_db(db_path)

    today = date.today()
    yesterday = today - timedelta(days=1)
    in_3_days = today + timedelta(days=3)
    in_7_days = today + timedelta(days=7)

    # Seed transactions to produce opening balance (yesterday) and current balance (today)
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        # Opening components: +100 -50 on/before yesterday => 50
        cur.execute(
            "INSERT INTO transactions(idempotency_key, account_id, posted_at, amount_cents, source, is_cleared) VALUES (?,?,?,?,?,?)",
            ("idem-a", 1, (yesterday - timedelta(days=1)).isoformat() + "T00:00:00Z", 100_00, "seed", 1),
        )
        cur.execute(
            "INSERT INTO transactions(idempotency_key, account_id, posted_at, amount_cents, source, is_cleared) VALUES (?,?,?,?,?,?)",
            ("idem-b", 1, yesterday.isoformat() + "T00:00:00Z", -50_00, "seed", 1),
        )
        # Today transaction to affect current balance only
        cur.execute(
            "INSERT INTO transactions(idempotency_key, account_id, posted_at, amount_cents, source, is_cleared) VALUES (?,?,?,?,?,?)",
            ("idem-c", 1, today.isoformat() + "T00:00:00Z", 25_00, "seed", 1),
        )

        # Commitment due in 7 days (monthly)
        cur.execute(
            "INSERT INTO commitments(name, amount_cents, due_rule, next_due_date, priority, account_id, flexible_window_days, category_id, type) VALUES (?,?,?,?,?,?,?,?,?)",
            ("Rent", 60_00, "MONTHLY", in_7_days.isoformat(), 1, 1, None, None, "bill"),
        )

        # Key event 3 days out with 5-day lead window
        cur.execute(
            "INSERT INTO key_spend_events(name, event_date, repeat_rule, planned_amount_cents, category_id, lead_time_days, shift_policy, account_id) VALUES (?,?,?,?,?,?,?,?)",
            ("Birthday", in_3_days.isoformat(), "ONE_OFF", 20_00, None, 5, "AS_SCHEDULED", 1),
        )
        conn.commit()
    finally:
        conn.close()

    # Point job to this DB
    monkeypatch.setenv("BUDGET_DB_PATH", str(db_path))

    digest = run_nightly_snapshot(horizon_days=30)

    # Snapshot row exists
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        row = cur.execute("SELECT COUNT(*) FROM forecast_snapshot").fetchone()
        assert row[0] >= 1
    finally:
        conn.close()

    # Digest has expected fields
    assert "current_balance_cents" in digest
    assert "safe_to_spend_today_cents" in digest
    assert "balances" in digest
    assert "top_commitments_next_14_days" in digest
    assert "upcoming_key_events" in digest

    # Current balance reflects today's + opening components (50 + 25)
    assert digest["current_balance_cents"] == 75_00

    # Upcoming key event within lead time is included
    names = [e["name"] for e in digest["upcoming_key_events"]]
    assert "Birthday" in names

    # Commitment in next 14 days is present
    comm_names = [c["name"] for c in digest["top_commitments_next_14_days"]]
    assert "Rent" in comm_names

