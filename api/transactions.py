from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional
import sqlite3

from fastapi import APIRouter, HTTPException, Query

from forecast.calendar import _default_db_path


router = APIRouter()


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _parse_accounts_param(val: str | None) -> list[int] | None:
    if not val:
        return None
    out: list[int] = []
    for part in val.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except Exception:
            continue
    return out or None


@router.get("/api/transactions")
def list_transactions(
    start: Optional[str] = Query(None, description="Start date YYYY-MM-DD (inclusive)"),
    end: Optional[str] = Query(None, description="End date YYYY-MM-DD (inclusive)"),
    accounts: Optional[str] = Query(None, description="Comma-separated account IDs to include"),
    cleared: Optional[str] = Query("all", description="1 for cleared only, 0 for uncleared only, all for both"),
    q: Optional[str] = Query(None, description="Search in payee or memo (case-insensitive)"),
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
):
    dbp = _default_db_path()
    try:
        start_d = date.fromisoformat(start) if start else None
        end_d = date.fromisoformat(end) if end else None
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date format; use YYYY-MM-DD")

    acct_ids = _parse_accounts_param(accounts)

    where = ["1=1"]
    params: list = []
    if start_d:
        where.append("DATE(t.posted_at) >= ?")
        params.append(start_d.isoformat())
    if end_d:
        where.append("DATE(t.posted_at) <= ?")
        params.append(end_d.isoformat())
    if acct_ids:
        marks = ",".join(["?"] * len(acct_ids))
        where.append(f"t.account_id IN ({marks})")
        params.extend([int(x) for x in acct_ids])
    if cleared in ("0", "1"):
        where.append("t.is_cleared = ?")
        params.append(int(cleared))
    if q:
        where.append("(LOWER(t.payee) LIKE ? OR LOWER(t.memo) LIKE ?)")
        needle = f"%{q.lower()}%"
        params.extend([needle, needle])

    sql = f"""
        SELECT t.idempotency_key, t.posted_at, t.amount_cents, t.payee, t.memo,
               t.source, t.category_id, t.is_cleared,
               a.id AS account_id, a.name AS account_name
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        WHERE {' AND '.join(where)}
        ORDER BY datetime(t.posted_at) DESC, t.idempotency_key DESC
        LIMIT ? OFFSET ?
    """
    params_paged = params + [int(limit), int(offset)]

    with _connect(dbp) as conn:
        rows = conn.execute(sql, params_paged).fetchall()
        total = conn.execute(
            f"SELECT COUNT(*) AS n FROM transactions t JOIN accounts a ON a.id=t.account_id WHERE {' AND '.join(where)}",
            params,
        ).fetchone()[0]

    return {
        "total": int(total),
        "count": len(rows),
        "items": [
            {
                "idempotency_key": r["idempotency_key"],
                "posted_at": r["posted_at"],
                "amount_cents": int(r["amount_cents"]),
                "payee": r["payee"],
                "memo": r["memo"],
                "source": r["source"],
                "category_id": int(r["category_id"]) if r["category_id"] is not None else None,
                "is_cleared": int(r["is_cleared"]) == 1,
                "account": {"id": int(r["account_id"]), "name": r["account_name"]},
            }
            for r in rows
        ],
    }

