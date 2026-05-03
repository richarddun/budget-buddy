"""Budget Targets API — Monthly envelope budgeting per category.

Endpoints:
  GET    /api/budget-targets               — List all targets, optionally filtered by month/category
  POST   /api/budget-targets               — Create or update a monthly target
  GET    /api/budget-targets/{id}          — Get a single target with progress
  DELETE /api/budget-targets/{id}          — Delete a target
  GET    /api/budget-targets/progress      — Get spending progress for current/all months
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from datetime import datetime as _datetime
import sqlite3

from fastapi import APIRouter, HTTPException, Query, Request

from forecast.calendar import _default_db_path
from security.deps import require_auth, require_csrf, rate_limit


router = APIRouter()


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _current_month_yyyymm() -> int:
    """Return current month as YYYYMM integer, e.g. 202605 for May 2026."""
    now = _datetime.utcnow()
    return now.year * 100 + now.month


def _month_start_end_iso(yyyymm: int) -> tuple[str, str]:
    """Return (start_date, end_date) ISO strings for a given YYYYMM."""
    year = yyyymm // 100
    month = yyyymm % 100
    if month == 12:
        next_year = year + 1
        next_month = 1
    else:
        next_year = year
        next_month = month + 1
    start = f"{year:04d}-{month:02d}-01"
    end = f"{next_year:04d}-{next_month:02d}-01"
    return start, end


def _baseline_month_yyyymm(month: int | None = None) -> int:
    """Return the baseline month for queries, defaulting to current month."""
    return month if month is not None else _current_month_yyyymm()


def _calculate_progress(
    conn: sqlite3.Connection,
    category_id: int,
    month: int,
    target_cents: int,
    rollover_cents: int = 0,
) -> dict:
    """Calculate spending progress against a target for a given month.

    Returns a dict with spent_cents, target_cents, rollover_cents, effective_target,
    remaining_cents, percentage, and status.
    """
    start_iso, end_iso = _month_start_end_iso(month)
    
    # Sum spending (negative amounts = outflow) in this category for the month
    row = conn.execute(
        """
        SELECT COALESCE(SUM(ABS(amount_cents)), 0) AS total_spent
        FROM transactions
        WHERE category_id = ?
          AND amount_cents < 0
          AND posted_at >= ?
          AND posted_at < ?
        """,
        (category_id, start_iso, end_iso),
    ).fetchone()
    spent_cents = int(row["total_spent"]) if row else 0
    
    effective_target = target_cents + rollover_cents
    remaining_cents = effective_target - spent_cents
    
    percentage = 0.0
    if effective_target > 0:
        percentage = round((spent_cents / effective_target) * 100, 1)
    
    if percentage >= 100:
        status = "exceeded"
    elif percentage >= 80:
        status = "warning"
    elif percentage >= 50:
        status = "moderate"
    else:
        status = "on_track"
    
    return {
        "spent_cents": spent_cents,
        "target_cents": target_cents,
        "rollover_cents": rollover_cents,
        "effective_target_cents": effective_target,
        "remaining_cents": remaining_cents,
        "percentage": percentage,
        "status": status,
    }


def _row_to_target(r: sqlite3.Row, progress: dict | None = None) -> dict:
    d = {
        "id": int(r["id"]),
        "category_id": int(r["category_id"]),
        "month": int(r["month"]),
        "target_amount_cents": int(r["target_amount_cents"]),
        "rollover": bool(r["rollover"]),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }
    if progress:
        d["progress"] = progress
    return d


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────

@router.get("/api/budget-targets")
def list_targets(
    month: Optional[int] = Query(None, description="Filter by YYYYMM (default: current month)"),
    category_id: Optional[int] = Query(None, description="Filter by category ID"),
    include_progress: bool = Query(False, description="Include spending progress"),
    include_rollovers: bool = Query(False, description="Include rollover amounts"),
):
    """List monthly budget targets. Supports filtering by month and/or category."""
    dbp = _default_db_path()
    with _connect(dbp) as conn:
        target_month = _baseline_month_yyyymm(month)
        
        query = "SELECT * FROM budget_targets WHERE month = ?"
        params: list = [target_month]
        
        if category_id is not None:
            query += " AND category_id = ?"
            params.append(category_id)
        
        query += " ORDER BY category_id ASC"
        
        rows = conn.execute(query, params).fetchall()
        
        items = []
        for r in rows:
            cat_id = int(r["category_id"])
            target_cents = int(r["target_amount_cents"])
            rollover_cents = 0
            
            # Calculate rollover amount if enabled
            if include_rollovers and r["rollover"]:
                prev_month = target_month - 1
                if prev_month % 100 == 0:
                    prev_month = (target_month // 100 - 1) * 100 + 12
                
                roll_row = conn.execute(
                    "SELECT COALESCE(SUM(rollover_amount_cents), 0) AS total FROM budget_rollovers WHERE category_id = ? AND to_month = ?",
                    (cat_id, target_month),
                ).fetchone()
                rollover_cents = int(roll_row["total"]) if roll_row else 0
            
            progress = None
            if include_progress:
                progress = _calculate_progress(conn, cat_id, target_month, target_cents, rollover_cents)
            
            item = _row_to_target(r, progress)
            if include_rollovers:
                item["rollover_cents"] = rollover_cents
            
            items.append(item)
        
        return {"count": len(items), "items": items, "month": target_month}


@router.post("/api/budget-targets")
async def create_or_update_target(request: Request):
    """Create or update a monthly budget target for a category.

    If a target already exists for this category+month, it is updated.
    
    Body:
      category_id (int, required)
      month (int, optional) — YYYYMM, defaults to current month
      target_amount_cents (int, required) — budget cap
      rollover (bool, optional) — carry over unused amount (default: false)
    """
    require_auth(request)
    require_csrf(request)
    rate_limit(request, scope="budget-targets-write")
    
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    
    category_id = payload.get("category_id")
    if category_id is None:
        raise HTTPException(status_code=400, detail="'category_id' is required")
    try:
        category_id = int(category_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="'category_id' must be an integer")
    
    month = payload.get("month", _current_month_yyyymm())
    try:
        month = int(month)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="'month' must be an integer (YYYYMM)")
    
    target_amount_cents = payload.get("target_amount_cents")
    if target_amount_cents is None:
        raise HTTPException(status_code=400, detail="'target_amount_cents' is required")
    try:
        target_amount_cents = int(target_amount_cents)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="'target_amount_cents' must be an integer")
    
    if target_amount_cents < 0:
        raise HTTPException(status_code=400, detail="'target_amount_cents' must be non-negative")
    
    rollover = bool(payload.get("rollover", False))
    
    dbp = _default_db_path()
    with _connect(dbp) as conn:
        # Verify category exists
        cat = conn.execute("SELECT 1 FROM categories WHERE id = ?", (category_id,)).fetchone()
        if not cat:
            raise HTTPException(status_code=404, detail=f"Category {category_id} not found")
        
        # Upsert
        existing = conn.execute(
            "SELECT id FROM budget_targets WHERE category_id = ? AND month = ?",
            (category_id, month),
        ).fetchone()
        
        now = _datetime.utcnow().isoformat(timespec="seconds") + "Z"
        
        if existing:
            conn.execute(
                """UPDATE budget_targets 
                   SET target_amount_cents = ?, rollover = ?, updated_at = ? 
                   WHERE id = ?""",
                (target_amount_cents, 1 if rollover else 0, now, int(existing["id"])),
            )
            new_id = int(existing["id"])
        else:
            cur = conn.execute(
                """INSERT INTO budget_targets (category_id, month, target_amount_cents, rollover, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (category_id, month, target_amount_cents, 1 if rollover else 0, now, now),
            )
            new_id = int(cur.lastrowid)
        
        conn.commit()
        
        row = conn.execute(
            "SELECT * FROM budget_targets WHERE id = ?", (new_id,)
        ).fetchone()
    
    return {"status": "ok", "target": _row_to_target(row)}


@router.get("/api/budget-targets/{target_id}")
def get_target(target_id: int, include_progress: bool = Query(False)):
    """Get a single budget target by ID, with optional progress calculation."""
    dbp = _default_db_path()
    with _connect(dbp) as conn:
        row = conn.execute(
            "SELECT bt.*, c.name AS category_name FROM budget_targets bt LEFT JOIN categories c ON c.id = bt.category_id WHERE bt.id = ?",
            (target_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Budget target not found")
        
        cat_id = int(row["category_id"])
        month = int(row["month"])
        target_cents = int(row["target_amount_cents"])
        rollover_cents = 0
        
        if row["rollover"]:
            roll_row = conn.execute(
                "SELECT COALESCE(SUM(rollover_amount_cents), 0) AS total FROM budget_rollovers WHERE category_id = ? AND to_month = ?",
                (cat_id, month),
            ).fetchone()
            rollover_cents = int(roll_row["total"]) if roll_row else 0
        
        progress = None
        if include_progress:
            progress = _calculate_progress(conn, cat_id, month, target_cents, rollover_cents)
        
        d = _row_to_target(row, progress)
        d["category_name"] = row["category_name"]
        d["rollover_cents"] = rollover_cents
        return d


@router.delete("/api/budget-targets/{target_id}")
async def delete_target(target_id: int, request: Request):
    """Delete a budget target."""
    require_auth(request)
    require_csrf(request)
    rate_limit(request, scope="budget-targets-write")
    
    dbp = _default_db_path()
    with _connect(dbp) as conn:
        row = conn.execute(
            "SELECT 1 FROM budget_targets WHERE id = ?", (target_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Budget target not found")
        
        conn.execute("DELETE FROM budget_targets WHERE id = ?", (target_id,))
        conn.commit()
    
    return {"status": "deleted", "id": target_id}


@router.get("/api/budget-targets/progress")
def get_progress(
    month: Optional[int] = Query(None, description="YYYYMM (default: current month)"),
    alert_threshold: int = Query(80, description="Percentage at which to trigger warnings (default: 80)"),
):
    """Get spending progress against all targets for a given month.

    Returns per-category progress, overall budget health, and any warnings
    for categories approaching or exceeding their targets.
    """
    dbp = _default_db_path()
    with _connect(dbp) as conn:
        target_month = _baseline_month_yyyymm(month)
        
        # Get all targets for the month
        targets = conn.execute(
            "SELECT bt.*, c.name AS category_name FROM budget_targets bt LEFT JOIN categories c ON c.id = bt.category_id WHERE bt.month = ? ORDER BY bt.id ASC",
            (target_month,),
        ).fetchall()
        
        categories_progress = []
        total_target_cents = 0
        total_spent_cents = 0
        total_rollover_cents = 0
        warnings = []
        
        for t in targets:
            cat_id = int(t["category_id"])
            target_cents = int(t["target_amount_cents"])
            rollover_enabled = bool(t["rollover"])
            rollover_cents = 0
            
            if rollover_enabled:
                roll_row = conn.execute(
                    "SELECT COALESCE(SUM(rollover_amount_cents), 0) AS total FROM budget_rollovers WHERE category_id = ? AND to_month = ?",
                    (cat_id, target_month),
                ).fetchone()
                rollover_cents = int(roll_row["total"]) if roll_row else 0
            
            progress = _calculate_progress(conn, cat_id, target_month, target_cents, rollover_cents)
            
            cat_entry = {
                "category_id": cat_id,
                "category_name": t["category_name"] or f"Category #{cat_id}",
                "target_cents": target_cents,
                "spent_cents": progress["spent_cents"],
                "rollover_cents": rollover_cents,
                "effective_target_cents": progress["effective_target_cents"],
                "remaining_cents": progress["remaining_cents"],
                "percentage": progress["percentage"],
                "status": progress["status"],
                "rollover_enabled": rollover_enabled,
            }
            categories_progress.append(cat_entry)
            
            total_target_cents += progress["effective_target_cents"]
            total_spent_cents += progress["spent_cents"]
            total_rollover_cents += rollover_cents
            
            # Generate warnings
            if progress["percentage"] >= alert_threshold:
                warnings.append({
                    "category_id": cat_id,
                    "category_name": cat_entry["category_name"],
                    "percentage": progress["percentage"],
                    "spent_cents": progress["spent_cents"],
                    "target_cents": progress["effective_target_cents"],
                    "remaining_cents": progress["remaining_cents"],
                    "severity": "exceeded" if progress["percentage"] >= 100 else "approaching",
                    "message": f"{cat_entry['category_name']}: "
                              f"{progress['percentage']:.0f}% used "
                              f"({progress['spent_cents'] / 100:.2f} / {progress['effective_target_cents'] / 100:.2f})"
                              + (f" — {progress['remaining_cents'] / 100:.2f} remaining" if progress["remaining_cents"] > 0 else " — OVER BUDGET!"),
                })
        
        total_remaining_cents = total_target_cents - total_spent_cents
        overall_pct = 0.0
        if total_target_cents > 0:
            overall_pct = round((total_spent_cents / total_target_cents) * 100, 1)
        
        return {
            "month": target_month,
            "categories": categories_progress,
            "summary": {
                "total_target_cents": total_target_cents,
                "total_spent_cents": total_spent_cents,
                "total_rollover_cents": total_rollover_cents,
                "total_remaining_cents": total_remaining_cents,
                "overall_percentage": overall_pct,
                "category_count": len(categories_progress),
                "warning_count": len(warnings),
            },
            "warnings": warnings,
            "alert_threshold": alert_threshold,
        }
