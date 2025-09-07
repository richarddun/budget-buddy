from __future__ import annotations

import os
import sqlite3
from datetime import date
from pathlib import Path
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, HTTPException, Query, Request

from forecast.calendar import _default_db_path


router = APIRouter()


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _require_csrf(request: Request) -> None:
    """If CSRF_TOKEN env var is set, require matching X-CSRF-Token header.

    If the env var is not set, do not enforce (useful for local/dev/tests).
    """
    token = os.getenv("CSRF_TOKEN")
    if token:
        header = request.headers.get("x-csrf-token") or request.headers.get("X-CSRF-Token")
        if header != token:
            raise HTTPException(status_code=403, detail="Invalid or missing CSRF token")


def _validate_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    # Required fields
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="'name' is required")
    event_date_raw = payload.get("event_date")
    try:
        event_date = date.fromisoformat(event_date_raw)
    except Exception:
        raise HTTPException(status_code=400, detail="'event_date' must be YYYY-MM-DD")

    # Optional/typed fields
    repeat_rule = (payload.get("repeat_rule") or None)
    planned_amount_cents = payload.get("planned_amount_cents")
    if planned_amount_cents is not None:
        try:
            planned_amount_cents = int(planned_amount_cents)
        except Exception:
            raise HTTPException(status_code=400, detail="'planned_amount_cents' must be integer cents")
    category_id = payload.get("category_id")
    if category_id is not None:
        try:
            category_id = int(category_id)
        except Exception:
            raise HTTPException(status_code=400, detail="'category_id' must be integer")
    lead_time_days = payload.get("lead_time_days")
    if lead_time_days is not None:
        try:
            lead_time_days = int(lead_time_days)
            if lead_time_days < 0:
                raise ValueError
        except Exception:
            raise HTTPException(status_code=400, detail="'lead_time_days' must be non-negative integer")
    shift_policy = payload.get("shift_policy")
    if shift_policy is not None:
        sp = str(shift_policy).strip().upper()
        if sp not in ("AS_SCHEDULED", "PREV_BUSINESS_DAY", "NEXT_BUSINESS_DAY"):
            raise HTTPException(status_code=400, detail="'shift_policy' invalid")
        shift_policy = sp
    account_id = payload.get("account_id")
    if account_id is not None:
        try:
            account_id = int(account_id)
        except Exception:
            raise HTTPException(status_code=400, detail="'account_id' must be integer")

    return {
        "name": name,
        "event_date": event_date,
        "repeat_rule": repeat_rule,
        "planned_amount_cents": planned_amount_cents,
        "category_id": category_id,
        "lead_time_days": lead_time_days,
        "shift_policy": shift_policy,
        "account_id": account_id,
    }


@router.get("/api/key-events")
def list_key_events(
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
) -> List[Dict[str, Any]]:
    dbp = _default_db_path()
    where = []
    params: list[Any] = []

    if from_date:
        try:
            date.fromisoformat(from_date)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid 'from' date; use YYYY-MM-DD")
        where.append("DATE(event_date) >= ?")
        params.append(from_date)
    if to_date:
        try:
            date.fromisoformat(to_date)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid 'to' date; use YYYY-MM-DD")
        where.append("DATE(event_date) <= ?")
        params.append(to_date)

    sql = (
        "SELECT id, name, event_date, repeat_rule, planned_amount_cents, category_id, lead_time_days, shift_policy, account_id "
        "FROM key_spend_events"
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY DATE(event_date) ASC, id ASC"

    with _connect(dbp) as conn:
        rows = conn.execute(sql, params).fetchall()
        return [
            {
                "id": int(r["id"]),
                "name": r["name"],
                "event_date": r["event_date"],
                "repeat_rule": r["repeat_rule"],
                "planned_amount_cents": int(r["planned_amount_cents"]) if r["planned_amount_cents"] is not None else None,
                "category_id": int(r["category_id"]) if r["category_id"] is not None else None,
                "lead_time_days": int(r["lead_time_days"]) if r["lead_time_days"] is not None else None,
                "shift_policy": r["shift_policy"],
                "account_id": int(r["account_id"]) if r["account_id"] is not None else None,
            }
            for r in rows
        ]


@router.post("/api/key-events")
async def upsert_key_event(request: Request) -> Dict[str, Any]:
    _require_csrf(request)
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    data = _validate_payload(payload)
    dbp = _default_db_path()
    with _connect(dbp) as conn:
        cur = conn.cursor()
        if payload.get("id") is not None:
            try:
                row_id = int(payload["id"])
            except Exception:
                raise HTTPException(status_code=400, detail="'id' must be integer")
            # Update existing
            cur.execute(
                """
                UPDATE key_spend_events
                SET name = ?, event_date = ?, repeat_rule = ?, planned_amount_cents = ?,
                    category_id = ?, lead_time_days = ?, shift_policy = ?, account_id = ?
                WHERE id = ?
                """,
                (
                    data["name"],
                    data["event_date"].isoformat(),
                    data["repeat_rule"],
                    data["planned_amount_cents"],
                    data["category_id"],
                    data["lead_time_days"],
                    data["shift_policy"],
                    data["account_id"],
                    row_id,
                ),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Key event not found")
            conn.commit()
            event_id = row_id
        else:
            # Insert new
            cur.execute(
                """
                INSERT INTO key_spend_events(name, event_date, repeat_rule, planned_amount_cents, category_id, lead_time_days, shift_policy, account_id)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    data["name"],
                    data["event_date"].isoformat(),
                    data["repeat_rule"],
                    data["planned_amount_cents"],
                    data["category_id"],
                    data["lead_time_days"],
                    data["shift_policy"],
                    data["account_id"],
                ),
            )
            conn.commit()
            event_id = int(cur.lastrowid)

        # Return the row
        row = conn.execute(
            "SELECT id, name, event_date, repeat_rule, planned_amount_cents, category_id, lead_time_days, shift_policy, account_id FROM key_spend_events WHERE id = ?",
            (event_id,),
        ).fetchone()
        return {
            "id": int(row["id"]),
            "name": row["name"],
            "event_date": row["event_date"],
            "repeat_rule": row["repeat_rule"],
            "planned_amount_cents": int(row["planned_amount_cents"]) if row["planned_amount_cents"] is not None else None,
            "category_id": int(row["category_id"]) if row["category_id"] is not None else None,
            "lead_time_days": int(row["lead_time_days"]) if row["lead_time_days"] is not None else None,
            "shift_policy": row["shift_policy"],
            "account_id": int(row["account_id"]) if row["account_id"] is not None else None,
        }


@router.delete("/api/key-events/{event_id}")
async def delete_key_event(event_id: int, request: Request) -> Dict[str, Any]:
    _require_csrf(request)
    dbp = _default_db_path()
    with _connect(dbp) as conn:
        cur = conn.execute("DELETE FROM key_spend_events WHERE id = ?", (event_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Key event not found")
        conn.commit()
        return {"status": "deleted", "id": event_id}

