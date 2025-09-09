from __future__ import annotations

from pathlib import Path
import sqlite3
from fastapi import APIRouter, HTTPException, Request
from security.deps import require_auth, require_csrf, rate_limit
import os
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


def _parse_overdraft_alert_thresholds(env_val: str | None) -> dict[int, int]:
    """Parse mapping like '1:-77500,2:-60000' into {account_id: threshold_cents}.

    Threshold is the level below which we should raise a reconciliation alert.
    """
    out: dict[int, int] = {}
    if not env_val:
        return out
    try:
        parts = [p.strip() for p in env_val.split(",") if p.strip()]
        for p in parts:
            k, v = p.split(":", 1)
            out[int(k.strip())] = int(v.strip())
    except Exception:
        return {}
    return out


@router.get("/api/accounts/floors")
def get_account_overdraft_alert_thresholds():
    """Expose per-account overdraft alert thresholds from env mapping.

    Env var: OVERDRAFT_ALERT_THRESHOLDS="1:-77500,2:-60000"
    """
    env = os.getenv("OVERDRAFT_ALERT_THRESHOLDS")
    mapping = _parse_overdraft_alert_thresholds(env)
    return {"thresholds": mapping}


@router.get("/api/accounts/anchors")
def list_account_anchors():
    dbp = _default_db_path()
    with _connect(dbp) as conn:
        rows = conn.execute(
            "SELECT account_id, anchor_date, anchor_balance_cents, COALESCE(min_floor_cents, 0) AS min_floor_cents FROM account_anchors"
        ).fetchall()
        return {
            "anchors": [
                {
                    "account_id": int(r["account_id"]),
                    "anchor_date": r["anchor_date"],
                    "anchor_balance_cents": int(r["anchor_balance_cents"]),
                    "min_floor_cents": int(r["min_floor_cents"]),
                }
                for r in rows
            ]
        }


@router.put("/api/accounts/{account_id}/anchor")
async def upsert_account_anchor(account_id: int, request: Request):
    """Upsert per-account anchor. Body fields:
    - anchor_date (YYYY-MM-DD, required)
    - anchor_balance_cents (int, required)
    - min_floor_cents (int, optional)
    """
    require_auth(request)
    require_csrf(request)
    rate_limit(request, scope="anchors-write")
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    try:
        ad_raw = (payload.get("anchor_date") or "").strip()
        from datetime import date

        # Validate format
        date.fromisoformat(ad_raw)
    except Exception:
        raise HTTPException(status_code=400, detail="'anchor_date' must be YYYY-MM-DD")
    try:
        bal = int(payload.get("anchor_balance_cents"))
    except Exception:
        raise HTTPException(status_code=400, detail="'anchor_balance_cents' must be integer cents")
    mfc = payload.get("min_floor_cents")
    try:
        mfc_int = int(mfc) if mfc is not None else None
    except Exception:
        raise HTTPException(status_code=400, detail="'min_floor_cents' must be integer cents")

    dbp = _default_db_path()
    with _connect(dbp) as conn:
        # Ensure account exists
        row = conn.execute("SELECT 1 FROM accounts WHERE id=?", (account_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Account not found")
        conn.execute(
            """
            INSERT INTO account_anchors(account_id, anchor_date, anchor_balance_cents, min_floor_cents)
            VALUES(?,?,?,?)
            ON CONFLICT(account_id) DO UPDATE SET
                anchor_date=excluded.anchor_date,
                anchor_balance_cents=excluded.anchor_balance_cents,
                min_floor_cents=excluded.min_floor_cents
            """,
            (account_id, ad_raw, bal, mfc_int),
        )
        conn.commit()
    return {
        "account_id": account_id,
        "anchor_date": ad_raw,
        "anchor_balance_cents": bal,
        "min_floor_cents": mfc_int,
        "status": "ok",
    }
