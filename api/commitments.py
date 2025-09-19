from __future__ import annotations

from pathlib import Path
from typing import Optional
from datetime import date as _date
import sqlite3

from fastapi import APIRouter, HTTPException, Request

from forecast.calendar import _default_db_path
from security.deps import require_auth, require_csrf, rate_limit


router = APIRouter()


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _monthly_equivalent_cents(amount_cents: int, due_rule: Optional[str]) -> int:
    if amount_cents is None:
        return 0
    rule = (due_rule or "MONTHLY").strip().upper()
    if rule in ("MONTHLY", "MONTHLY_BY_DATE"):
        return int(amount_cents)
    if rule == "WEEKLY":
        return int(round(amount_cents * (52.0 / 12.0)))
    if rule == "BIWEEKLY":
        return int(round(amount_cents * (26.0 / 12.0)))
    if rule in ("ANNUAL", "YEARLY"):
        return int(round(amount_cents / 12.0))
    # Fallback: treat as monthly
    return int(amount_cents)


@router.get("/api/commitments")
def list_commitments():
    """List confirmed recurring commitments with a running total and monthly equivalent total.

    Returns JSON with items, total_cents (raw sum), monthly_equivalent_cents (normalized), and count.
    """
    dbp = _default_db_path()
    with _connect(dbp) as conn:
        rows = conn.execute(
            """
            SELECT id, name, amount_cents, due_rule, next_due_date, priority,
                   account_id, flexible_window_days, category_id, type
            FROM commitments
            ORDER BY name ASC, id ASC
            """
        ).fetchall()

    items = []
    total_cents = 0
    total_monthly_equiv = 0
    for r in rows:
        amt = int(r["amount_cents"]) if r["amount_cents"] is not None else 0
        total_cents += amt
        meq = _monthly_equivalent_cents(amt, r["due_rule"])
        total_monthly_equiv += meq
        items.append(
            {
                "id": int(r["id"]),
                "name": r["name"],
                "amount_cents": amt,
                "due_rule": r["due_rule"],
                "monthly_equivalent_cents": meq,
                "next_due_date": r["next_due_date"],
                "priority": int(r["priority"]) if r["priority"] is not None else None,
                "account_id": int(r["account_id"]) if r["account_id"] is not None else None,
                "flexible_window_days": int(r["flexible_window_days"]) if r["flexible_window_days"] is not None else None,
                "category_id": int(r["category_id"]) if r["category_id"] is not None else None,
                "type": r["type"],
            }
        )

    return {
        "count": len(items),
        "total_cents": int(total_cents),
        "monthly_equivalent_cents": int(total_monthly_equiv),
        "items": items,
    }


@router.post("/api/commitments")
async def create_commitment(request: Request):
    """Create a new commitment row.

    Body fields:
    - name (str, required)
    - amount_cents (int) or amount_eur (float)
    - due_rule (str, default 'MONTHLY')
    - next_due_date (YYYY-MM-DD, optional)
    - account_id (int, required)
    - priority (int, optional; default 1)
    - flexible_window_days (int, optional; default 0)
    - category_id (int, optional)
    - type (str, default 'bill')
    """
    require_auth(request)
    require_csrf(request)
    rate_limit(request, scope="commitments-write")
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="'name' is required")
    amt_c = payload.get("amount_cents")
    amt_e = payload.get("amount_eur")
    if amt_c is None and amt_e is None:
        raise HTTPException(status_code=400, detail="Provide amount_cents or amount_eur")
    try:
        amount_cents = int(amt_c) if amt_c is not None else int(round(float(amt_e) * 100.0))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid amount")

    due_rule = (payload.get("due_rule") or "MONTHLY").strip().upper()
    next_due_date = (payload.get("next_due_date") or None)
    acct_id = payload.get("account_id")
    try:
        account_id = int(acct_id) if acct_id is not None else None
    except Exception:
        raise HTTPException(status_code=400, detail="'account_id' must be an integer")
    priority = payload.get("priority")
    priority_i = int(priority) if priority is not None else 1
    flex = payload.get("flexible_window_days")
    flex_i = int(flex) if flex is not None else 0
    cat = payload.get("category_id")
    category_id = int(cat) if cat is not None else None
    type_ = (payload.get("type") or "bill").strip()

    dbp = _default_db_path()
    with _connect(dbp) as conn:
        # Validate account
        if account_id is not None:
            row = conn.execute("SELECT 1 FROM accounts WHERE id = ?", (account_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Account not found")
        cur = conn.execute(
            """
            INSERT INTO commitments(name, amount_cents, due_rule, next_due_date, priority, account_id, flexible_window_days, category_id, type)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                name,
                amount_cents,
                due_rule,
                next_due_date,
                priority_i,
                account_id,
                flex_i,
                category_id,
                type_,
            ),
        )
        new_id = int(cur.lastrowid)
        row = conn.execute(
            "SELECT id, name, amount_cents, due_rule, next_due_date, priority, account_id, flexible_window_days, category_id, type FROM commitments WHERE id = ?",
            (new_id,),
        ).fetchone()
    return {
        "status": "ok",
        "commitment": {
            "id": int(row["id"]),
            "name": row["name"],
            "amount_cents": int(row["amount_cents"]),
            "due_rule": row["due_rule"],
            "next_due_date": row["next_due_date"],
            "priority": int(row["priority"]) if row["priority"] is not None else None,
            "account_id": int(row["account_id"]) if row["account_id"] is not None else None,
            "flexible_window_days": int(row["flexible_window_days"]) if row["flexible_window_days"] is not None else None,
            "category_id": int(row["category_id"]) if row["category_id"] is not None else None,
            "type": row["type"],
            "monthly_equivalent_cents": _monthly_equivalent_cents(int(row["amount_cents"]), row["due_rule"]),
        },
    }


@router.put("/api/commitments/{commitment_id}")
async def update_commitment(commitment_id: int, request: Request):
    """Update a commitment. Accepts partial body with any of the fields from create_commitment."""
    require_auth(request)
    require_csrf(request)
    rate_limit(request, scope="commitments-write")
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    fields: list[str] = []
    params: list = []

    def set_field(col: str, val):
        fields.append(f"{col} = ?")
        params.append(val)

    if "name" in payload and payload.get("name") is not None:
        name = str(payload.get("name")).strip()
        if not name:
            raise HTTPException(status_code=400, detail="'name' cannot be empty")
        set_field("name", name)

    if payload.get("amount_cents") is not None or payload.get("amount_eur") is not None:
        try:
            amt_c = payload.get("amount_cents")
            amt_e = payload.get("amount_eur")
            amount_cents = int(amt_c) if amt_c is not None else int(round(float(amt_e) * 100.0))
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid amount")
        set_field("amount_cents", amount_cents)

    if "due_rule" in payload and payload.get("due_rule") is not None:
        set_field("due_rule", str(payload.get("due_rule")).strip().upper())

    if "next_due_date" in payload:
        nd = payload.get("next_due_date")
        # allow None to clear
        set_field("next_due_date", nd)

    if "priority" in payload and payload.get("priority") is not None:
        try:
            set_field("priority", int(payload.get("priority")))
        except Exception:
            raise HTTPException(status_code=400, detail="'priority' must be integer")

    if "account_id" in payload:
        acct = payload.get("account_id")
        if acct is not None:
            try:
                account_id = int(acct)
            except Exception:
                raise HTTPException(status_code=400, detail="'account_id' must be integer")
            # Validate account exists
            dbp = _default_db_path()
            with _connect(dbp) as conn:
                row = conn.execute("SELECT 1 FROM accounts WHERE id = ?", (account_id,)).fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Account not found")
        else:
            account_id = None
        set_field("account_id", account_id)

    if "flexible_window_days" in payload and payload.get("flexible_window_days") is not None:
        try:
            set_field("flexible_window_days", int(payload.get("flexible_window_days")))
        except Exception:
            raise HTTPException(status_code=400, detail="'flexible_window_days' must be integer")

    if "category_id" in payload:
        cat = payload.get("category_id")
        try:
            cid = int(cat) if cat is not None else None
        except Exception:
            raise HTTPException(status_code=400, detail="'category_id' must be integer")
        set_field("category_id", cid)

    if "type" in payload and payload.get("type") is not None:
        set_field("type", str(payload.get("type")))

    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    dbp = _default_db_path()
    with _connect(dbp) as conn:
        # Ensure exists
        row = conn.execute("SELECT 1 FROM commitments WHERE id = ?", (commitment_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Commitment not found")
        params.append(commitment_id)
        conn.execute(f"UPDATE commitments SET {', '.join(fields)} WHERE id = ?", params)
        conn.commit()
        row = conn.execute(
            "SELECT id, name, amount_cents, due_rule, next_due_date, priority, account_id, flexible_window_days, category_id, type FROM commitments WHERE id = ?",
            (commitment_id,),
        ).fetchone()
    return {
        "status": "ok",
        "commitment": {
            "id": int(row["id"]),
            "name": row["name"],
            "amount_cents": int(row["amount_cents"]),
            "due_rule": row["due_rule"],
            "next_due_date": row["next_due_date"],
            "priority": int(row["priority"]) if row["priority"] is not None else None,
            "account_id": int(row["account_id"]) if row["account_id"] is not None else None,
            "flexible_window_days": int(row["flexible_window_days"]) if row["flexible_window_days"] is not None else None,
            "category_id": int(row["category_id"]) if row["category_id"] is not None else None,
            "type": row["type"],
            "monthly_equivalent_cents": _monthly_equivalent_cents(int(row["amount_cents"]), row["due_rule"]),
        },
    }


@router.delete("/api/commitments/{commitment_id}")
async def delete_commitment(commitment_id: int, request: Request):
    require_auth(request)
    require_csrf(request)
    rate_limit(request, scope="commitments-write")
    dbp = _default_db_path()
    with _connect(dbp) as conn:
        cur = conn.execute("DELETE FROM commitments WHERE id = ?", (commitment_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Commitment not found")
        conn.commit()
    return {"status": "deleted", "id": int(commitment_id)}
