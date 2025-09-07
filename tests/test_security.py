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


def test_auth_and_csrf_enforced_when_configured(tmp_path, monkeypatch):
    # Point app to isolated DB
    db_path = tmp_path / "budget_sec.db"
    _init_test_db(db_path)
    monkeypatch.setenv("BUDGET_DB_PATH", str(db_path))
    # Enable protections
    monkeypatch.setenv("ADMIN_TOKEN", "admintest")
    monkeypatch.setenv("CSRF_TOKEN", "csrftest")

    app = load_app()
    client = TestClient(app)

    # 1) No headers -> unauthorized
    r1 = client.post(
        "/api/key-events",
        json={"name": "X", "event_date": "2025-01-01"},
    )
    assert r1.status_code == 401

    # 2) Only auth -> missing CSRF
    r2 = client.post(
        "/api/key-events",
        json={"name": "X", "event_date": "2025-01-01"},
        headers={"Authorization": "Bearer admintest"},
    )
    assert r2.status_code == 403

    # 3) Only CSRF -> missing auth
    r3 = client.post(
        "/api/key-events",
        json={"name": "X", "event_date": "2025-01-01"},
        headers={"X-CSRF-Token": "csrftest"},
    )
    assert r3.status_code == 401

    # 4) Both -> OK
    r4 = client.post(
        "/api/key-events",
        json={"name": "X", "event_date": "2025-01-01"},
        headers={"Authorization": "Bearer admintest", "X-CSRF-Token": "csrftest"},
    )
    assert r4.status_code == 200


def test_rate_limit_for_admin_routes(tmp_path, monkeypatch):
    # Minimal DB for export assembly isn't necessary; hitting rate limiter scope via q/export is fine
    db_path = tmp_path / "budget_rate.db"
    # Create minimal tables used by packs/export to avoid failures
    conn = sqlite3.connect(db_path)
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
        cur.execute(
            "INSERT INTO accounts(id, name, type, currency, is_active) VALUES (?,?,?,?,?)",
            (1, "Checking", "depository", "USD", 1),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setenv("BUDGET_DB_PATH", str(db_path))
    monkeypatch.setenv("ADMIN_TOKEN", "admintest")
    monkeypatch.setenv("CSRF_TOKEN", "csrftest")
    monkeypatch.setenv("ADMIN_RATE_LIMIT", "2/60s")

    app = load_app()
    client = TestClient(app)
    headers = {"Authorization": "Bearer admintest", "X-CSRF-Token": "csrftest"}

    # Two requests pass
    r1 = client.post("/api/q/export", json={"pack": "affordability_snapshot", "format": "csv"}, headers=headers)
    r2 = client.post("/api/q/export", json={"pack": "affordability_snapshot", "format": "csv"}, headers=headers)
    assert r1.status_code == 200
    assert r2.status_code == 200
    # Third should be rate-limited in same window
    r3 = client.post("/api/q/export", json={"pack": "affordability_snapshot", "format": "csv"}, headers=headers)
    assert r3.status_code == 429

