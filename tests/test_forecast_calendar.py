from __future__ import annotations

import os
import sqlite3
from datetime import date
from pathlib import Path

from forecast.calendar import compute_balances, expand_calendar


def _init_test_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        cur = conn.cursor()
        # Minimal schema for this test (subset of 0001_init.sql)
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS accounts (
              id INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              type TEXT NOT NULL,
              currency TEXT NOT NULL,
              is_active INTEGER NOT NULL DEFAULT 1
            );
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

        # Seed a dummy account
        cur.execute(
            "INSERT INTO accounts(id, name, type, currency, is_active) VALUES (?,?,?,?,?)",
            (1, "Checking", "depository", "USD", 1),
        )

        conn.commit()
    finally:
        conn.close()


def test_expand_and_balance_with_shifts(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "budget_test.db"
    _init_test_db(db_path)

    # Seed items
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        # Inflow scheduled on Saturday 2025-01-04, weekly, should shift to Monday 2025-01-06
        cur.execute(
            """
            INSERT INTO scheduled_inflows(name, amount_cents, due_rule, next_due_date, account_id, type)
            VALUES (?,?,?,?,?,?)
            """,
            ("Payday", 100_00, "WEEKLY", "2025-01-04", 1, "payroll"),
        )

        # Commitment due on Sunday 2025-01-05, monthly, flexible window 2 days -> shift to Friday 2025-01-03
        cur.execute(
            """
            INSERT INTO commitments(name, amount_cents, due_rule, next_due_date, priority, account_id, flexible_window_days, category_id, type)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            ("Rent", 50_00, "MONTHLY", "2025-01-05", 1, 1, 2, None, "bill"),
        )

        # Key event on Sunday 2025-01-05 with AS_SCHEDULED (no shift)
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

    # Point module to this DB
    monkeypatch.setenv("BUDGET_DB_PATH", str(db_path))

    start = date(2025, 1, 1)
    end = date(2025, 1, 10)
    entries = expand_calendar(start, end)

    # Expect 3 entries
    assert len(entries) == 3

    # Verify dates and shift behaviors
    # Commitment shifted to Friday 2025-01-03
    rent = next(e for e in entries if e.type == "commitment")
    assert rent.name == "Rent"
    assert rent.date == date(2025, 1, 3)
    assert rent.shift_applied is True
    assert rent.policy == "PREV_BUSINESS_DAY"
    assert rent.amount_cents == -50_00

    # Key event stays on Sunday
    bday = next(e for e in entries if e.type == "key_event")
    assert bday.date == date(2025, 1, 5)
    assert bday.shift_applied is False
    assert bday.policy == "AS_SCHEDULED"
    assert bday.amount_cents == -20_00

    # Inflow moves to Monday 2025-01-06
    payday = next(e for e in entries if e.type == "inflow")
    assert payday.date == date(2025, 1, 6)
    assert payday.shift_applied is True
    assert payday.policy == "NEXT_BUSINESS_DAY"
    assert payday.amount_cents == 100_00

    # Check deterministic ordering by date then type
    ordered = [(e.date.isoformat(), e.type) for e in entries]
    assert ordered == [
        ("2025-01-03", "commitment"),
        ("2025-01-05", "key_event"),
        ("2025-01-06", "inflow"),
    ]

    # Validate balances per day present in entries
    balances = compute_balances(0, entries)
    # After 2025-01-03: -50
    assert balances[date(2025, 1, 3)] == -50_00
    # After 2025-01-05: -70
    assert balances[date(2025, 1, 5)] == -70_00
    # After 2025-01-06: +30
    assert balances[date(2025, 1, 6)] == 30_00

