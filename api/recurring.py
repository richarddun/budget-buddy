"""REST API for recurring transaction template management."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Any

from fastapi import APIRouter, HTTPException, Request, Query

from forecast.calendar import _default_db_path
from security.deps import require_auth, require_csrf, rate_limit
from jobs.recurring_templates import (
    list_templates,
    run_recurring_auto_create,
    generate_templates_from_commitments,
)

logger = logging.getLogger("uvicorn.error")
router = APIRouter()

TEMPLATE_RULES = ["MONTHLY", "WEEKLY", "BIWEEKLY", "ANNUAL", "ONE_OFF"]
TEMPLATE_TYPES = ["expense", "income"]


def _connect(db_path: Path):
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _int_or_none(val: Any) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


# ─── List ────────────────────────────────────────────────────────────────────


@router.get("/api/recurring")
def api_list_recurring():
    """List all recurring templates with account names and metadata."""
    dbp = _default_db_path()
    try:
        templates = list_templates(dbp)
    except Exception as exc:
        logger.exception("Failed to list recurring templates")
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "count": len(templates),
        "items": templates,
    }


# ─── Create ──────────────────────────────────────────────────────────────────


@router.post("/api/recurring")
async def api_create_recurring(request: Request):
    """Create a new recurring template.

    Body (JSON):
    - name: str (required)
    - amount_cents: int or amount_eur: float (required)
    - due_rule: str (default 'MONTHLY'); one of MONTHLY, WEEKLY, BIWEEKLY, ANNUAL, ONE_OFF
    - next_due_date: str | None (YYYY-MM-DD)
    - account_id: int (required)
    - category_id: int | None
    - payee: str | None (defaults to name)
    - memo: str | None
    - type: str (default 'expense'); expense or income
    - auto_create: bool (default True)
    - source_commitment_id: int | None
    - source_inflow_id: int | None
    """
    require_auth(request)
    require_csrf(request)
    rate_limit(request, scope="recurring-write")

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
    if due_rule not in TEMPLATE_RULES:
        raise HTTPException(status_code=400, detail=f"Invalid due_rule; must be one of {TEMPLATE_RULES}")

    next_due_date = (payload.get("next_due_date") or "").strip() or None

    account_id = _int_or_none(payload.get("account_id"))
    if account_id is None:
        raise HTTPException(status_code=400, detail="'account_id' is required")

    category_id = _int_or_none(payload.get("category_id"))
    payee = (payload.get("payee") or "").strip() or name
    memo = (payload.get("memo") or "").strip() or None
    ttype = (payload.get("type") or "expense").strip().lower()
    if ttype not in TEMPLATE_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid type; must be one of {TEMPLATE_TYPES}")
    auto_create = bool(payload.get("auto_create", True))
    source_commitment_id = _int_or_none(payload.get("source_commitment_id"))
    source_inflow_id = _int_or_none(payload.get("source_inflow_id"))

    dbp = _default_db_path()
    conn = _connect(dbp)
    try:
        # Validate account
        row = conn.execute("SELECT 1 FROM accounts WHERE id = ?", (account_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Account not found")

        # Validate category if provided
        if category_id is not None:
            row = conn.execute("SELECT 1 FROM categories WHERE id = ?", (category_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Category not found")

        # Validate commitment link if provided
        if source_commitment_id is not None:
            row = conn.execute("SELECT 1 FROM commitments WHERE id = ?", (source_commitment_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Commitment not found")

        # Validate inflow link if provided
        if source_inflow_id is not None:
            row = conn.execute("SELECT 1 FROM scheduled_inflows WHERE id = ?", (source_inflow_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Scheduled inflow not found")

        cur = conn.execute(
            """
            INSERT INTO recurring_templates(
                name, amount_cents, due_rule, next_due_date,
                account_id, category_id, payee, memo, type,
                auto_create, source_commitment_id, source_inflow_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name, amount_cents, due_rule, next_due_date,
                account_id, category_id, payee, memo, ttype,
                1 if auto_create else 0,
                source_commitment_id, source_inflow_id,
            ),
        )
        conn.commit()
        new_id = int(cur.lastrowid)

        # Fetch the created row
        r = conn.execute(
            "SELECT * FROM recurring_templates WHERE id = ?",
            (new_id,),
        ).fetchone()

        return {
            "status": "ok",
            "template": {
                "id": int(r["id"]),
                "name": r["name"],
                "amount_cents": int(r["amount_cents"]),
                "due_rule": r["due_rule"],
                "next_due_date": r["next_due_date"],
                "account_id": int(r["account_id"]),
                "category_id": int(r["category_id"]) if r["category_id"] is not None else None,
                "payee": r["payee"],
                "memo": r["memo"],
                "type": r["type"],
                "auto_create": bool(r["auto_create"]),
                "source_commitment_id": int(r["source_commitment_id"]) if r["source_commitment_id"] is not None else None,
                "source_inflow_id": int(r["source_inflow_id"]) if r["source_inflow_id"] is not None else None,
                "is_active": bool(r["is_active"]),
            },
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(f"Failed to create recurring template: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        conn.close()


# ─── Update ──────────────────────────────────────────────────────────────────


@router.put("/api/recurring/{template_id}")
async def api_update_recurring(template_id: int, request: Request):
    """Update a recurring template. Accepts partial body."""
    require_auth(request)
    require_csrf(request)
    rate_limit(request, scope="recurring-write")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    dbp = _default_db_path()
    conn = _connect(dbp)
    try:
        # Ensure exists
        row = conn.execute("SELECT 1 FROM recurring_templates WHERE id = ?", (template_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Template not found")

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
            rule = str(payload.get("due_rule")).strip().upper()
            if rule not in TEMPLATE_RULES:
                raise HTTPException(status_code=400, detail=f"Invalid due_rule; must be one of {TEMPLATE_RULES}")
            set_field("due_rule", rule)

        if "next_due_date" in payload:
            set_field("next_due_date", payload.get("next_due_date"))

        if "account_id" in payload:
            aid = _int_or_none(payload.get("account_id"))
            if aid is not None:
                row2 = conn.execute("SELECT 1 FROM accounts WHERE id = ?", (aid,)).fetchone()
                if not row2:
                    raise HTTPException(status_code=404, detail="Account not found")
            set_field("account_id", aid)

        if "category_id" in payload:
            set_field("category_id", _int_or_none(payload.get("category_id")))

        if "payee" in payload:
            set_field("payee", (payload.get("payee") or "").strip() or None)

        if "memo" in payload:
            set_field("memo", (payload.get("memo") or "").strip() or None)

        if "type" in payload and payload.get("type") is not None:
            ttype = str(payload.get("type")).strip().lower()
            if ttype not in TEMPLATE_TYPES:
                raise HTTPException(status_code=400, detail=f"Invalid type; must be one of {TEMPLATE_TYPES}")
            set_field("type", ttype)

        if "auto_create" in payload:
            set_field("auto_create", 1 if payload.get("auto_create") else 0)

        if "is_active" in payload:
            set_field("is_active", 1 if payload.get("is_active") else 0)

        if not fields:
            raise HTTPException(status_code=400, detail="No fields to update")

        # Always update the updated_at timestamp
        fields.append("updated_at = datetime('now')")

        params.append(template_id)
        conn.execute(
            f"UPDATE recurring_templates SET {', '.join(fields)} WHERE id = ?",
            params,
        )
        conn.commit()

        r = conn.execute("SELECT * FROM recurring_templates WHERE id = ?", (template_id,)).fetchone()
        return {
            "status": "ok",
            "template": {
                "id": int(r["id"]),
                "name": r["name"],
                "amount_cents": int(r["amount_cents"]),
                "due_rule": r["due_rule"],
                "next_due_date": r["next_due_date"],
                "account_id": int(r["account_id"]),
                "category_id": int(r["category_id"]) if r["category_id"] is not None else None,
                "payee": r["payee"],
                "memo": r["memo"],
                "type": r["type"],
                "auto_create": bool(r["auto_create"]),
                "is_active": bool(r["is_active"]),
            },
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(f"Failed to update recurring template: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        conn.close()


# ─── Delete ──────────────────────────────────────────────────────────────────


@router.delete("/api/recurring/{template_id}")
async def api_delete_recurring(template_id: int, request: Request):
    """Delete a recurring template."""
    require_auth(request)
    require_csrf(request)
    rate_limit(request, scope="recurring-write")

    dbp = _default_db_path()
    conn = _connect(dbp)
    try:
        cur = conn.execute("DELETE FROM recurring_templates WHERE id = ?", (template_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Template not found")
        conn.commit()
    finally:
        conn.close()

    return {"status": "deleted", "id": template_id}


# ─── Run auto-create ─────────────────────────────────────────────────────────


@router.post("/api/recurring/auto-create")
async def api_run_auto_create(request: Request):
    """Manually trigger auto-creation of transactions from due templates.

    Body (JSON) optional:
    - dry_run: bool (default False)
    - lookahead_days: int (default 1)
    """
    require_auth(request)
    require_csrf(request)
    rate_limit(request, scope="recurring-write")

    try:
        payload = {}
        if request.headers.get("content-type", "").startswith("application/json"):
            payload = await request.json()
    except Exception:
        payload = {}

    dry_run = bool(payload.get("dry_run", False))
    lookahead = int(payload.get("lookahead_days", 1))

    dbp = _default_db_path()
    try:
        result = run_recurring_auto_create(dbp, lookahead_days=lookahead, dry_run=dry_run)
    except Exception as exc:
        logger.exception(f"Auto-create failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))

    return result


# ─── Sync from commitments/inflows ──────────────────────────────────────────


@router.post("/api/recurring/sync-from-commitments")
async def api_sync_from_commitments(request: Request):
    """Generate recurring templates from existing commitments and scheduled_inflows
    that don't already have linked templates."""
    require_auth(request)
    require_csrf(request)
    rate_limit(request, scope="recurring-write")

    dbp = _default_db_path()
    try:
        result = generate_templates_from_commitments(dbp)
    except Exception as exc:
        logger.exception(f"Sync from commitments failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))

    return result


# ─── Instance history ────────────────────────────────────────────────────────


@router.get("/api/recurring/instances")
def api_list_instances(
    template_id: Optional[int] = Query(None, description="Filter by template ID"),
    status: Optional[str] = Query(None, description="Filter by status (pending/created/skipped/error)"),
    limit: int = Query(100, ge=1, le=500),
):
    """List recurring instance records (transaction generation history)."""
    dbp = _default_db_path()
    conn = _connect(dbp)
    try:
        where = ["1=1"]
        params: list = []
        if template_id is not None:
            where.append("ri.template_id = ?")
            params.append(template_id)
        if status:
            where.append("ri.status = ?")
            params.append(status)

        rows = conn.execute(
            f"""
            SELECT ri.id, ri.template_id, ri.due_date, ri.idempotency_key,
                   ri.created_at, ri.status,
                   rt.name AS template_name
            FROM recurring_instances ri
            LEFT JOIN recurring_templates rt ON rt.id = ri.template_id
            WHERE {' AND '.join(where)}
            ORDER BY ri.id DESC
            LIMIT ?
            """,
            params + [int(limit)],
        ).fetchall()

        return {
            "count": len(rows),
            "items": [
                {
                    "id": int(r["id"]),
                    "template_id": int(r["template_id"]),
                    "template_name": r["template_name"],
                    "due_date": r["due_date"],
                    "idempotency_key": r["idempotency_key"],
                    "created_at": r["created_at"],
                    "status": r["status"],
                }
                for r in rows
            ],
        }
    finally:
        conn.close()
