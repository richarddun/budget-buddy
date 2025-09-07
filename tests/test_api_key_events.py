from __future__ import annotations

import importlib
import os
import sqlite3
import sys
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


def test_key_events_crud_and_filtering(tmp_path, monkeypatch):
    db_path = tmp_path / "budget_key_events.db"
    _init_test_db(db_path)

    # Point app to this DB and set CSRF token
    monkeypatch.setenv("BUDGET_DB_PATH", str(db_path))
    monkeypatch.setenv("CSRF_TOKEN", "testtoken")

    app = load_app()
    client = TestClient(app)

    base_headers = {"X-CSRF-Token": "testtoken"}

    today = date.today()
    in_5 = today + timedelta(days=5)
    in_10 = today + timedelta(days=10)

    # Create
    res = client.post(
        "/api/key-events",
        json={
            "name": "Birthday",
            "event_date": in_5.isoformat(),
            "repeat_rule": "ONE_OFF",
            "planned_amount_cents": 2500,
            "category_id": None,
            "lead_time_days": 7,
            "shift_policy": "AS_SCHEDULED",
            "account_id": 1,
        },
        headers=base_headers,
    )
    assert res.status_code == 200, res.text
    event = res.json()
    assert event["id"] > 0
    assert event["name"] == "Birthday"
    assert event["event_date"] == in_5.isoformat()

    # Update
    eid = event["id"]
    res2 = client.post(
        "/api/key-events",
        json={
            "id": eid,
            "name": "Birthday Party",
            "event_date": in_10.isoformat(),
            "repeat_rule": "ANNUAL",
            "planned_amount_cents": 3000,
            "category_id": None,
            "lead_time_days": 10,
            "shift_policy": "NEXT_BUSINESS_DAY",
            "account_id": 1,
        },
        headers=base_headers,
    )
    assert res2.status_code == 200, res2.text
    event2 = res2.json()
    assert event2["id"] == eid
    assert event2["name"] == "Birthday Party"
    assert event2["event_date"] == in_10.isoformat()
    assert event2["repeat_rule"] == "ANNUAL"
    assert event2["planned_amount_cents"] == 3000
    assert event2["lead_time_days"] == 10
    assert event2["shift_policy"] == "NEXT_BUSINESS_DAY"

    # Filtered GET (window that includes the updated date only)
    res3 = client.get(f"/api/key-events?from={in_10.isoformat()}&to={in_10.isoformat()}")
    assert res3.status_code == 200
    items = res3.json()
    assert any(it["id"] == eid for it in items)

    # Filtered GET (window that excludes) => may exclude depending on range
    res4 = client.get(f"/api/key-events?from={in_5.isoformat()}&to={in_5.isoformat()}")
    assert res4.status_code == 200
    assert all(it["event_date"] != in_5.isoformat() for it in res4.json())

    # Delete
    res5 = client.delete(f"/api/key-events/{eid}", headers=base_headers)
    assert res5.status_code == 200
    assert res5.json().get("status") == "deleted"

    # Ensure gone
    res6 = client.get(f"/api/key-events?from={in_10.isoformat()}&to={in_10.isoformat()}")
    assert res6.status_code == 200
    assert all(it["id"] != eid for it in res6.json())

    # Validation: missing name
    bad = client.post(
        "/api/key-events", json={"event_date": today.isoformat()}, headers=base_headers
    )
    assert bad.status_code == 400

    # Validation: bad date
    bad2 = client.post(
        "/api/key-events", json={"name": "X", "event_date": "2025-02-30"}, headers=base_headers
    )
    assert bad2.status_code == 400

