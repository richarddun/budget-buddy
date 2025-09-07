from __future__ import annotations

import importlib
import os
import sqlite3
import sys
import time
from datetime import date, timedelta
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


def _init_minimal_db(path: Path) -> None:
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
        # A couple of recurring items to make the calendar non-trivial
        cur.execute(
            "INSERT INTO scheduled_inflows(name, amount_cents, due_rule, next_due_date, account_id, type) VALUES (?,?,?,?,?,?)",
            ("Payday", 250_00, "WEEKLY", date.today().isoformat(), 1, "payroll"),
        )
        cur.execute(
            "INSERT INTO commitments(name, amount_cents, due_rule, next_due_date, priority, account_id, flexible_window_days, category_id, type) VALUES (?,?,?,?,?,?,?,?,?)",
            ("Rent", 1200_00, "MONTHLY", date.today().isoformat(), 1, 1, 2, None, "bill"),
        )
        conn.commit()
    finally:
        conn.close()


def test_forecast_120d_latency_and_overview_size(tmp_path, monkeypatch):
    db_path = tmp_path / "perf.db"
    _init_minimal_db(db_path)

    monkeypatch.setenv("BUDGET_DB_PATH", str(db_path))

    app = load_app()
    client = TestClient(app)

    start = date.today().isoformat()
    end = (date.today() + timedelta(days=120)).isoformat()

    # Warmup request (exclude initialization costs from timing)
    r0 = client.get("/api/forecast/calendar", params={"start": start, "end": end, "buffer_floor": 0})
    assert r0.status_code == 200

    # Measure a few runs and take median
    samples = []
    for _ in range(3):
        t0 = time.perf_counter()
        resp = client.get("/api/forecast/calendar", params={"start": start, "end": end, "buffer_floor": 0})
        dt = (time.perf_counter() - t0) * 1000.0
        assert resp.status_code == 200
        samples.append(dt)
    samples.sort()
    median_ms = samples[1]

    assert median_ms <= 150.0, f"Forecast median latency {median_ms:.2f}ms exceeds 150ms budget"

    # Dashboard/overview payload size budget (<= 200KB)
    ro = client.get("/api/overview")
    assert ro.status_code == 200
    size_bytes = len(ro.content or b"")
    assert size_bytes <= 200 * 1024, f"Overview JSON size {size_bytes} bytes exceeds 200KB budget"

