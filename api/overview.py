from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Optional, Dict, Any

import os
import sqlite3
from fastapi import APIRouter

from forecast.calendar import expand_calendar, compute_balances, _default_db_path
from api.forecast import compute_opening_balance_cents


router = APIRouter()


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _buffer_floor_cents() -> int:
    try:
        return int(os.getenv("BUFFER_FLOOR_CENTS", "0"))
    except Exception:
        return 0


def _latest_snapshot_info(db_path: Path) -> Dict[str, Optional[str]]:
    """Return latest snapshot metadata if present: created_at, horizon_start, horizon_end."""
    info = {"created_at": None, "horizon_start": None, "horizon_end": None}
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            SELECT created_at, horizon_start, horizon_end
            FROM forecast_snapshot
            ORDER BY created_at DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
        if row:
            info["created_at"] = row["created_at"]
            info["horizon_start"] = row["horizon_start"]
            info["horizon_end"] = row["horizon_end"]
    return info


@router.get("/api/overview")
def get_overview_digest() -> Dict[str, Any]:
    """Return a minimal overview digest for the UI header cards.

    Includes:
    - current_balance_cents (sum of cleared across active accounts as of today)
    - safe_to_spend_today_cents (today end-of-day minus buffer floor)
    - health_score (0-100 heuristic based on buffer/cliff proximity)
    - health_band (emoji string)
    - snapshot metadata for staleness display
    """
    dbp = _default_db_path()

    # Establish horizon for balance computation (prefer latest snapshot horizon if present)
    meta = _latest_snapshot_info(dbp)
    today = date.today()
    try:
        # Parse from snapshot if available
        start = date.fromisoformat(meta["horizon_start"]) if meta["horizon_start"] else today
        end = date.fromisoformat(meta["horizon_end"]) if meta["horizon_end"] else today + timedelta(days=120)
    except Exception:
        start = today
        end = today + timedelta(days=120)

    # Opening balance for horizon and balances across horizon
    opening_as_of = start - timedelta(days=1)
    opening_balance = compute_opening_balance_cents(as_of=opening_as_of, db_path=dbp)
    entries = expand_calendar(start, end, db_path=dbp)
    balances = compute_balances(opening_balance, entries)

    # Core values
    buffer_floor = _buffer_floor_cents()
    today_eod = balances.get(today, opening_balance)
    current_balance = compute_opening_balance_cents(as_of=today, db_path=dbp)
    safe_to_spend = max(today_eod - buffer_floor, 0)

    # Heuristic health score: start from 100, penalize if below buffer soon
    # - If next cliff within 7 days -> heavy penalty
    # - If below buffer today -> near 0
    # - Otherwise scale with safe_to_spend relative to buffer (cap 100)
    next_cliff_days: Optional[int] = None
    for d in sorted(balances.keys()):
        if d >= today and balances[d] < buffer_floor:
            next_cliff_days = (d - today).days
            break

    if today_eod < buffer_floor:
        health_score = 5
    elif buffer_floor > 0:
        ratio = min(max(safe_to_spend / buffer_floor, 0.0), 2.0)  # cap at 2x buffer
        base = min(int(ratio * 60), 90)  # up to 90 from ratio
        if next_cliff_days is not None and next_cliff_days <= 7:
            penalty = 40 - (next_cliff_days * 4)  # 40..12
        else:
            penalty = 0
        health_score = max(min(base + 10 - penalty, 100), 0)
    else:
        # No buffer configured; base on whether balances trend negative soon
        if next_cliff_days is None:
            health_score = 90
        elif next_cliff_days <= 7:
            health_score = 40
        else:
            health_score = 70

    if health_score >= 70:
        health_band = "🟢"
    elif health_score >= 40:
        health_band = "🟡"
    else:
        health_band = "🔴"

    return {
        "current_balance_cents": int(current_balance),
        "safe_to_spend_today_cents": int(safe_to_spend),
        "health_score": int(health_score),
        "health_band": health_band,
        "buffer_floor_cents": int(buffer_floor),
        "snapshot": {
            "created_at": meta["created_at"],
            "horizon_start": meta["horizon_start"],
            "horizon_end": meta["horizon_end"],
            "is_stale": bool(meta["created_at"] and (meta["created_at"][:10] != today.isoformat())),
        },
        "horizon": {"start": start.isoformat(), "end": end.isoformat()},
    }

