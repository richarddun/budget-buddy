from __future__ import annotations

from pathlib import Path
import sqlite3
from fastapi import APIRouter
from forecast.calendar import _default_db_path

router = APIRouter()


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


@router.get("/api/accounts")
def list_accounts():
    dbp = _default_db_path()
    with _connect(dbp) as conn:
        rows = conn.execute(
            "SELECT id, name, type, currency, is_active FROM accounts ORDER BY is_active DESC, name ASC"
        ).fetchall()
    return {
        "accounts": [
            {
                "id": int(r["id"]),
                "name": r["name"],
                "type": r["type"],
                "currency": r["currency"],
                "is_active": int(r["is_active"]) == 1,
            }
            for r in rows
        ]
    }

