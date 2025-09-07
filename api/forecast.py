from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional, List

import sqlite3
from fastapi import APIRouter, HTTPException, Query
import json

from forecast.calendar import Entry, compute_balances, expand_calendar, _default_db_path
from forecast.blended_stats import compute_daily_stats, compute_weekday_multipliers


router = APIRouter()


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _tz_name() -> str:
    import os

    return os.getenv("SCHED_TZ") or os.getenv("TZ") or "UTC"


def _today_tz() -> date:
    try:
        from zoneinfo import ZoneInfo  # type: ignore

        tz = ZoneInfo(_tz_name())
        return datetime.now(tz).date()
    except Exception:
        return datetime.utcnow().date()


def _load_key_event_lead_times(conn: sqlite3.Connection) -> dict[int, Optional[int]]:
    lead: dict[int, Optional[int]] = {}
    for row in conn.execute("SELECT id, lead_time_days FROM key_spend_events"):
        lead[int(row["id"])] = int(row["lead_time_days"]) if row["lead_time_days"] is not None else None
    return lead


def _ui_marker(entry: Entry) -> Optional[str]:
    if entry.type == "commitment":
        return "📄"
    if entry.type == "key_event":
        n = entry.name.lower()
        if "birthday" in n or "bday" in n:
            return "🎂"
        if "christmas" in n or "xmas" in n or "holiday" in n:
            return "🎄"
        return "🎯"
    return None


def compute_opening_balance_cents(as_of: Optional[date] = None, *, db_path: Optional[Path] = None) -> int:
    """Compute opening balance as sum of cleared transactions across active accounts.

    If `as_of` is provided, only include transactions with posted_at on or before that date.
    posted_at is stored as ISO text; we compare on the DATE(posted_at) in SQLite for safety.
    """
    dbp = db_path or _default_db_path()
    with _connect(dbp) as conn:
        if as_of is None:
            cur = conn.execute(
                """
                SELECT COALESCE(SUM(t.amount_cents), 0) AS bal
                FROM transactions t
                JOIN accounts a ON a.id = t.account_id
                WHERE a.is_active = 1 AND t.is_cleared = 1
                """
            )
        else:
            cur = conn.execute(
                """
                SELECT COALESCE(SUM(t.amount_cents), 0) AS bal
                FROM transactions t
                JOIN accounts a ON a.id = t.account_id
                WHERE a.is_active = 1 AND t.is_cleared = 1
                  AND DATE(t.posted_at) <= ?
                """,
                (as_of.isoformat(),),
            )
        row = cur.fetchone()
        return int(row["bal"] if row and row["bal"] is not None else 0)


@router.get("/api/forecast/calendar")
def get_forecast_calendar(
    start: str = Query(..., description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD"),
    buffer_floor: int = Query(0, description="Buffer floor in cents"),
):
    # Validate dates
    try:
        start_d = date.fromisoformat(start)
        end_d = date.fromisoformat(end)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format; use YYYY-MM-DD")
    if end_d < start_d:
        raise HTTPException(status_code=400, detail="end must be on or after start")

    # Opening balance as of the day before the start of horizon
    opening_as_of = start_d - timedelta(days=1)
    dbp = _default_db_path()
    opening_balance = compute_opening_balance_cents(as_of=opening_as_of, db_path=dbp)

    # Expand entries and compute balances
    entries = expand_calendar(start_d, end_d, db_path=dbp)
    balances = compute_balances(opening_balance, entries)

    # Compute min balance and date deterministically
    min_balance_cents = None
    min_balance_date = None
    if balances:
        # Sort by date to ensure deterministic selection when multiple equal minima
        items = sorted(balances.items(), key=lambda kv: kv[0])
        min_balance_cents = items[0][1]
        min_balance_date = items[0][0]
        for d, bal in items:
            if bal < min_balance_cents:
                min_balance_cents = bal
                min_balance_date = d

    # Enrich entries with UI marker and key-event lead-window flag.
    # For deterministic behavior in UI/tests, treat `today` as the start of the requested horizon.
    today = start_d
    lead_map: dict[int, Optional[int]] = {}
    with _connect(dbp) as conn:
        try:
            lead_map = _load_key_event_lead_times(conn)
        except Exception:
            lead_map = {}

    enriched = []
    for e in entries:
        lead_days = lead_map.get(e.source_id) if e.type == "key_event" else None
        is_within = None
        if e.type == "key_event" and lead_days is not None:
            days_until = (e.date - today).days
            is_within = 0 <= days_until <= int(lead_days)
        enriched.append(
            {
                "date": e.date.isoformat(),
                "type": e.type,
                "name": e.name,
                "amount_cents": e.amount_cents,
                "source_id": e.source_id,
                "shift_applied": e.shift_applied,
                "policy": e.policy,
                "ui_marker": _ui_marker(e),
                "is_within_lead_window": is_within,
            }
        )

    resp = {
        "opening_balance_cents": opening_balance,
        "entries": enriched,
        "balances": {d.isoformat(): bal for d, bal in balances.items()},
        "min_balance_cents": min_balance_cents,
        "min_balance_date": min_balance_date.isoformat() if min_balance_date else None,
        "meta": {
            "opening_balance_strategy": "sum_cleared_active_accounts_as_of(start_minus_one)",
            "buffer_floor": buffer_floor,
            "below_buffer": (min_balance_cents is not None and buffer_floor is not None and min_balance_cents < buffer_floor),
            "db_path": str(dbp),
            "today": today.isoformat(),
        },
    }
    return resp


def _load_transactions_for_stats(db_path: Path, window_days: int = 180) -> list[dict]:
    """Load recent transactions joined with category names for heuristic filtering.

    Returns a list of dicts suitable for blended_stats helpers.
    """
    rows: list[dict] = []
    with _connect(db_path) as conn:
        # Limit to a reasonable window by posted_at
        cur = conn.execute(
            """
            SELECT t.amount_cents,
                   t.posted_at,
                   t.category_id,
                   c.name AS category_name,
                   cg.name AS category_group
            FROM transactions t
            LEFT JOIN categories c ON c.id = t.category_id
            LEFT JOIN categories cg ON cg.id = c.parent_id
            WHERE DATE(t.posted_at) >= DATE('now', ?)
            """,
            (f"-{int(window_days)} days",),
        )
        for r in cur:
            rows.append(
                {
                    "amount_cents": int(r["amount_cents"]) if r["amount_cents"] is not None else 0,
                    "posted_at": r["posted_at"],
                    "category_id": r["category_id"],
                    "category_name": r["category_name"],
                    "category_group": r["category_group"],
                }
            )
    return rows


@router.get("/api/forecast/blended")
def get_forecast_blended(
    start: str = Query(..., description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD"),
    mu_daily: Optional[int] = Query(None, description="Mean daily variable spend in cents"),
    sigma_daily: Optional[int] = Query(None, description="Std dev of daily variable spend in cents"),
    weekday_mult: Optional[str] = Query(None, description="JSON array of 7 floats for weekday multipliers, Mon..Sun"),
    band_k: float = Query(0.8, description="Band width multiplier (k * sigma)"),
):
    # Validate dates
    try:
        start_d = date.fromisoformat(start)
        end_d = date.fromisoformat(end)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format; use YYYY-MM-DD")
    if end_d < start_d:
        raise HTTPException(status_code=400, detail="end must be on or after start")

    dbp = _default_db_path()

    # Deterministic baseline calendar balances for the horizon
    opening_as_of = start_d - timedelta(days=1)
    opening_balance = compute_opening_balance_cents(as_of=opening_as_of, db_path=dbp)
    entries = expand_calendar(start_d, end_d, db_path=dbp)
    balances_cal = compute_balances(opening_balance, entries)

    # Parameters: parse or compute from stats
    mults: List[float]
    if weekday_mult:
        try:
            arr = json.loads(weekday_mult)
            if not (isinstance(arr, list) and len(arr) == 7):
                raise ValueError
            mults = [float(x) for x in arr]
        except Exception:
            raise HTTPException(status_code=400, detail="weekday_mult must be a JSON array of 7 numbers")
    else:
        txns = _load_transactions_for_stats(dbp, window_days=180)
        mults = compute_weekday_multipliers(txns, window_days=180)

    if mu_daily is None or sigma_daily is None:
        txns = _load_transactions_for_stats(dbp, window_days=180)
        mu_c, sigma_c = compute_daily_stats(txns, window_days=180)
        if mu_daily is None:
            mu_daily = mu_c
        if sigma_daily is None:
            sigma_daily = sigma_c

    # Compute blended baseline and bands for each date we have a baseline point
    # We use the same sparse date set as the deterministic balances for consistency with the chart.
    blended: dict[date, int] = {}
    band_lower: dict[date, int] = {}
    band_upper: dict[date, int] = {}

    for d, bal in sorted(balances_cal.items(), key=lambda kv: kv[0]):
        w = d.weekday()  # 0=Mon..6=Sun
        expected = int(round((mu_daily or 0) * float(mults[w])))
        base = int(bal) - expected
        k_sigma = float(band_k) * float(sigma_daily or 0)
        delta = int(round(k_sigma))
        blended[d] = base
        band_lower[d] = base - delta
        band_upper[d] = base + delta

    resp = {
        "baseline_calendar": {d.isoformat(): v for d, v in balances_cal.items()},
        "baseline_blended": {d.isoformat(): v for d, v in blended.items()},
        "bands": {
            "lower": {d.isoformat(): v for d, v in band_lower.items()},
            "upper": {d.isoformat(): v for d, v in band_upper.items()},
        },
        "params": {
            "mu_daily_cents": int(mu_daily or 0),
            "sigma_daily_cents": int(sigma_daily or 0),
            "weekday_mult": mults,
            "k": band_k,
        },
        "meta": {"horizon": {"start": start_d.isoformat(), "end": end_d.isoformat()}},
    }
    return resp
