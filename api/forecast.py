from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional, List

import sqlite3
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi import Body
import json

from forecast.calendar import Entry, compute_balances, expand_calendar, _default_db_path
from forecast.blended_stats import compute_daily_stats, compute_weekday_multipliers
from config import (
    MONTE_CARLO_ENABLED,
    MONTE_CARLO_MAX_ITER,
    MONTE_CARLO_DEFAULT_ITER,
    MONTE_CARLO_DEFAULT_SEED,
)
from config import SALARY_DOM, SALARY_MIN_CENTS
import random
from security.deps import require_auth


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


def _ledger_daily_deltas(conn: sqlite3.Connection, start: date, end: date) -> dict[date, int]:
    """Return mapping of date -> sum(amount_cents) for cleared transactions on that date.

    Joins accounts to ensure only active accounts are considered.
    """
    rows = conn.execute(
        """
        SELECT DATE(t.posted_at) AS d, COALESCE(SUM(t.amount_cents), 0) AS delta
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        WHERE a.is_active = 1
          AND t.is_cleared = 1
          AND DATE(t.posted_at) >= ? AND DATE(t.posted_at) <= ?
        GROUP BY DATE(t.posted_at)
        ORDER BY DATE(t.posted_at)
        """,
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    out: dict[date, int] = {}
    for r in rows:
        try:
            d = date.fromisoformat(str(r[0]))
            out[d] = int(r[1] or 0)
        except Exception:
            continue
    return out


@router.get("/api/forecast/history")
def get_forecast_history(
    start: str = Query(..., description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD"),
    accounts: str | None = Query(None, description="Comma-separated account IDs to include"),
):
    """Return ledger-based daily balances between start and end (inclusive).

    Uses cleared transactions across active accounts. Opening balance is computed
    as of the day before `start` and daily deltas are applied forward.
    """
    try:
        start_d = date.fromisoformat(start)
        end_d = date.fromisoformat(end)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format; use YYYY-MM-DD")
    if end_d < start_d:
        raise HTTPException(status_code=400, detail="end must be on or after start")

    dbp = _default_db_path()
    opening_as_of = start_d - timedelta(days=1)
    acc_set = _parse_accounts_param(accounts)
    opening = compute_opening_balance_cents(as_of=opening_as_of, db_path=dbp, accounts=acc_set)

    with _connect(dbp) as conn:
        deltas = _ledger_daily_deltas(conn, start_d, end_d) if not accounts else _ledger_daily_deltas(conn, start_d, end_d)
        acc_set = _parse_accounts_param(accounts)
        if acc_set:
            # Re-run with filtering
            qmarks = ",".join(["?"] * len(acc_set))
            rows = conn.execute(
                f"""
                SELECT DATE(t.posted_at) AS d, COALESCE(SUM(t.amount_cents), 0) AS delta
                FROM transactions t
                JOIN accounts a ON a.id = t.account_id
                WHERE a.is_active = 1 AND t.is_cleared = 1
                  AND a.id IN ({qmarks})
                  AND DATE(t.posted_at) >= ? AND DATE(t.posted_at) <= ?
                GROUP BY DATE(t.posted_at)
                ORDER BY DATE(t.posted_at)
                """,
                (*[int(x) for x in sorted(acc_set)], start_d.isoformat(), end_d.isoformat()),
            ).fetchall()
            deltas = {}
            for r in rows:
                try:
                    d0 = date.fromisoformat(str(r[0]))
                    deltas[d0] = int(r[1] or 0)
                except Exception:
                    continue

    # Walk days and build balances
    balances: dict[date, int] = {}
    running = opening
    d = start_d
    while d <= end_d:
        running = running + (deltas.get(d, 0))
        balances[d] = running
        d = d + timedelta(days=1)

    # Heuristic salary checkpoints (optional): near configured day-of-month with inflow over threshold
    checkpoints: list[dict] = []
    if SALARY_DOM and 1 <= int(SALARY_DOM) <= 31 and int(SALARY_MIN_CENTS) > 0:
        from calendar import monthrange

        def target_for_month(y: int, m: int) -> date:
            dom = int(SALARY_DOM)
            last = monthrange(y, m)[1]
            d = min(dom, last)
            return date(y, m, d)

        # Build windows per month and match deltas
        d = start_d
        seen_dates: set[date] = set()
        while d <= end_d:
            tgt = target_for_month(d.year, d.month)
            win_start = tgt - timedelta(days=3)
            win_end = tgt + timedelta(days=3)
            # Iterate days in window within overall range
            cursor = max(win_start, start_d)
            while cursor <= min(win_end, end_d):
                if cursor in deltas and deltas[cursor] >= int(SALARY_MIN_CENTS) and cursor not in seen_dates:
                    checkpoints.append({
                        "date": cursor.isoformat(),
                        "amount_cents": int(deltas[cursor]),
                    })
                    seen_dates.add(cursor)
                cursor = cursor + timedelta(days=1)
            # Jump to first day of next month
            if d.month == 12:
                d = date(d.year + 1, 1, 1)
            else:
                d = date(d.year, d.month + 1, 1)

    return {
        "opening_balance_cents": opening,
        "balances": {d.isoformat(): v for d, v in balances.items()},
        "meta": {
            "source": "ledger",
            "db_path": str(dbp),
            "window_days": (end_d - start_d).days + 1,
        },
        "checkpoints": checkpoints,
    }


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


def compute_opening_balance_cents(
    as_of: Optional[date] = None,
    *,
    db_path: Optional[Path] = None,
    accounts: Optional[set[int]] = None,
) -> int:
    """Compute opening balance as sum of cleared transactions across active accounts.

    If `as_of` is provided, only include transactions with posted_at on or before that date.
    posted_at is stored as ISO text; we compare on the DATE(posted_at) in SQLite for safety.
    """
    dbp = db_path or _default_db_path()
    with _connect(dbp) as conn:
        base = [
            "SELECT COALESCE(SUM(t.amount_cents), 0) AS bal",
            "FROM transactions t",
            "JOIN accounts a ON a.id = t.account_id",
            "WHERE a.is_active = 1 AND t.is_cleared = 1",
        ]
        params: list = []
        if as_of is not None:
            base.append("AND DATE(t.posted_at) <= ?")
            params.append(as_of.isoformat())
        if accounts:
            qmarks = ",".join(["?"] * len(accounts))
            base.append(f"AND a.id IN ({qmarks})")
            params.extend(int(x) for x in sorted(accounts))
        sql = "\n".join(base)
        cur = conn.execute(sql, params)
        row = cur.fetchone()
        return int(row["bal"] if row and row["bal"] is not None else 0)


def _parse_accounts_param(val: str | None) -> set[int] | None:
    if not val:
        return None
    out: set[int] = set()
    for part in val.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except Exception:
            continue
    return out or None


@router.get("/api/forecast/calendar")
def get_forecast_calendar(
    start: str = Query(..., description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD"),
    buffer_floor: int = Query(0, description="Buffer floor in cents"),
    accounts: str | None = Query(None, description="Comma-separated account IDs to include"),
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
    opening_balance = compute_opening_balance_cents(as_of=opening_as_of, db_path=dbp, accounts=accounts_set)

    # Expand entries and compute balances
    accounts_set = _parse_accounts_param(accounts)
    entries = expand_calendar(start_d, end_d, db_path=dbp, accounts=accounts_set)
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


@router.get("/api/forecast/calendar/debug")
def get_forecast_calendar_debug(
    request: Request,
    start: str = Query(..., description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD"),
    accounts: str | None = Query(None, description="Comma-separated account IDs to include"),
):
    """Explain the deterministic calendar computation day-by-day for diagnostics.

    Returns opening balance as of start-1, all expanded entries, and a per-day
    breakdown with opening→delta→closing and the items contributing to delta.
    Protected by admin token when configured.
    """
    # Auth (no-op if ADMIN_TOKEN not set)
    try:
        require_auth(request)
    except Exception:
        # Keep consistent error behavior
        raise

    try:
        start_d = date.fromisoformat(start)
        end_d = date.fromisoformat(end)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format; use YYYY-MM-DD")
    if end_d < start_d:
        raise HTTPException(status_code=400, detail="end must be on or after start")

    dbp = _default_db_path()
    opening_as_of = start_d - timedelta(days=1)
    opening_balance = compute_opening_balance_cents(as_of=opening_as_of, db_path=dbp)

    acc_set = _parse_accounts_param(accounts)
    entries = expand_calendar(start_d, end_d, db_path=dbp, accounts=acc_set)
    balances = compute_balances(opening_balance, entries)

    # Group entries by date
    by_day: dict[date, list[dict]] = {}
    for e in entries:
        by_day.setdefault(e.date, []).append(
            {
                "type": e.type,
                "name": e.name,
                "amount_cents": e.amount_cents,
                "source_id": e.source_id,
                "shift_applied": e.shift_applied,
                "policy": e.policy,
            }
        )

    # Walk horizon days deterministically
    rows: list[dict] = []
    running = opening_balance
    d = start_d
    while d <= end_d:
        items = by_day.get(d, [])
        delta = sum(int(it["amount_cents"]) for it in items) if items else 0
        closing = balances.get(d, running + delta)
        rows.append(
            {
                "date": d.isoformat(),
                "opening_balance_cents": running,
                "delta_cents": delta,
                "closing_balance_cents": closing,
                "items": items,
            }
        )
        running = closing
        d = d + timedelta(days=1)

    return {
        "opening_balance_cents": opening_balance,
        "balances": {d.isoformat(): b for d, b in balances.items()},
        "rows": rows,
        "entries": [
            {
                "date": e.date.isoformat(),
                "type": e.type,
                "name": e.name,
                "amount_cents": e.amount_cents,
                "source_id": e.source_id,
                "shift_applied": e.shift_applied,
                "policy": e.policy,
            }
            for e in entries
        ],
        "meta": {"db_path": str(dbp), "accounts": sorted(list(acc_set)) if acc_set else None},
    }


@router.get("/api/transactions/export")
def export_transactions(
    request: Request,
    start: str = Query(..., alias="from", description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD"),
    accounts: str | None = Query(None, description="Comma-separated account IDs"),
    include_uncleared: bool = Query(False, description="Include uncleared transactions"),
    limit: int = Query(5000, ge=1, le=100000),
    offset: int = Query(0, ge=0),
):
    """Export transactions in a date window for diagnostics.

    Protected by admin token when configured. Returns JSON rows with account and
    category names when available.
    """
    require_auth(request)
    try:
        start_d = date.fromisoformat(start)
        end_d = date.fromisoformat(end)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format; use YYYY-MM-DD")
    if end_d < start_d:
        raise HTTPException(status_code=400, detail="end must be on or after start")

    acc_set = _parse_accounts_param(accounts)
    q = [
        "SELECT t.posted_at, t.amount_cents, t.payee, t.memo, t.account_id, a.name AS account_name,",
        "       t.category_id, c.name AS category_name, t.is_cleared, t.source, t.external_id",
        "FROM transactions t",
        "LEFT JOIN accounts a ON a.id = t.account_id",
        "LEFT JOIN categories c ON c.id = t.category_id",
        "WHERE DATE(t.posted_at) >= ? AND DATE(t.posted_at) <= ?",
    ]
    params: list = [start_d.isoformat(), end_d.isoformat()]
    if not include_uncleared:
        q.append("AND t.is_cleared = 1")
    if acc_set:
        q.append(f"AND t.account_id IN ({','.join(['?']*len(acc_set))})")
        params.extend(int(x) for x in sorted(acc_set))
    q.append("ORDER BY DATE(t.posted_at) ASC, t.idempotency_key ASC")
    q.append("LIMIT ? OFFSET ?")
    params.extend([int(limit), int(offset)])

    dbp = _default_db_path()
    rows_out: list[dict] = []
    with _connect(dbp) as conn:
        cur = conn.execute("\n".join(q), params)
        for r in cur:
            rows_out.append(
                {
                    "posted_at": r["posted_at"],
                    "amount_cents": int(r["amount_cents"]),
                    "payee": r["payee"],
                    "memo": r["memo"],
                    "account_id": int(r["account_id"]) if r["account_id"] is not None else None,
                    "account_name": r["account_name"],
                    "category_id": int(r["category_id"]) if r["category_id"] is not None else None,
                    "category_name": r["category_name"],
                    "is_cleared": bool(r["is_cleared"]),
                    "source": r["source"],
                    "external_id": r["external_id"],
                }
            )

    return {"transactions": rows_out, "count": len(rows_out), "db_path": str(dbp)}


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


@router.get("/api/forecast/monte-carlo")
def get_forecast_monte_carlo(
    start: str = Query(..., description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD"),
    mu_daily: Optional[int] = Query(None, description="Mean daily variable spend in cents"),
    sigma_daily: Optional[int] = Query(None, description="Std dev of daily variable spend in cents"),
    weekday_mult: Optional[str] = Query(None, description="JSON array of 7 floats for weekday multipliers, Mon..Sun"),
    iterations: Optional[int] = Query(None, description="Number of Monte Carlo iterations (<= max)"),
    seed: Optional[int] = Query(None, description="RNG seed for reproducibility"),
):
    # Feature flag gate
    if not MONTE_CARLO_ENABLED:
        raise HTTPException(status_code=404, detail="Monte Carlo endpoint is disabled")

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

    # Iterations/seed
    iters = int(iterations or MONTE_CARLO_DEFAULT_ITER)
    iters = max(1, min(iters, int(MONTE_CARLO_MAX_ITER)))
    rng = random.Random(int(seed) if seed is not None else MONTE_CARLO_DEFAULT_SEED)

    # For each date, simulate variable spend draws and compute P10/P90 bands
    # We use the same sparse date set as the deterministic balances for consistency with charts.
    p10: dict[date, int] = {}
    p90: dict[date, int] = {}

    # Precompute per-date mean (modulated by weekday multiplier)
    items = sorted(balances_cal.items(), key=lambda kv: kv[0])
    for d, bal in items:
        w = d.weekday()  # 0=Mon..6=Sun
        mean = float(mu_daily or 0) * float(mults[w])
        sigma = float(sigma_daily or 0)
        draws: list[float] = []
        for _ in range(iters):
            x = rng.gauss(mean, sigma)
            # Clamp to >= 0 (no negative spend magnitude)
            if x < 0:
                x = 0.0
            draws.append(x)
        # Compute percentiles on draws
        draws.sort()
        def _pct(data: List[float], q: float) -> float:
            if not data:
                return 0.0
            # Simple nearest-rank interpolation
            idx = max(0, min(len(data) - 1, int(round(q * (len(data) - 1)))))
            return data[idx]

        d10 = _pct(draws, 0.10)
        d90 = _pct(draws, 0.90)
        # Bands are baseline minus spend
        lower = int(round(bal - d90))
        upper = int(round(bal - d10))
        p10[d] = lower
        p90[d] = upper

    resp = {
        "baseline_calendar": {d.isoformat(): v for d, v in balances_cal.items()},
        "bands": {
            "p10": {d.isoformat(): v for d, v in p10.items()},
            "p90": {d.isoformat(): v for d, v in p90.items()},
        },
        "params": {
            "mu_daily_cents": int(mu_daily or 0),
            "sigma_daily_cents": int(sigma_daily or 0),
            "weekday_mult": mults,
            "iterations": iters,
            "seed": int(seed if seed is not None else MONTE_CARLO_DEFAULT_SEED),
        },
        "meta": {"horizon": {"start": start_d.isoformat(), "end": end_d.isoformat()}},
    }
    return resp


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


def _binary_search_max_spend(is_safe, lo: int, hi: int) -> int:
    """Generic binary search on integer domain to find the max value in [lo, hi]
    such that `is_safe(x)` is True. Assumes monotonic predicate (True then False).
    """
    best = lo
    while lo <= hi:
        mid = (lo + hi) // 2
        if is_safe(mid):
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


@router.post("/api/forecast/simulate-spend")
def post_forecast_simulate_spend(
    payload: dict = Body(
        ..., description="{date, amount_cents, mode?, buffer_floor?, horizon_days?, tight_threshold_cents?}"
    ),
):
    """Simulate a hypothetical discretionary spend on a date and evaluate safety.

    Input JSON:
    - date: YYYY-MM-DD (required)
    - amount_cents: int (required; positive spend)
    - mode: 'deterministic' | 'blended' (optional; blended is reference-only)
    - buffer_floor: int cents (optional; default 0)
    - horizon_days: int (optional; default 120)
    - tight_threshold_cents: int (optional; default 1000)
    """
    try:
        spend_date = date.fromisoformat(str(payload.get("date")))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid or missing 'date' (YYYY-MM-DD)")
    try:
        amount_cents = int(payload.get("amount_cents"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid or missing 'amount_cents' (int cents)")
    if amount_cents < 0:
        raise HTTPException(status_code=400, detail="amount_cents must be non-negative (spend)")

    mode = str(payload.get("mode") or "deterministic").lower()
    buffer_floor = int(payload.get("buffer_floor") or 0)
    horizon_days = int(payload.get("horizon_days") or 120)
    tight_thresh = int(payload.get("tight_threshold_cents") or 1000)

    if horizon_days <= 0:
        raise HTTPException(status_code=400, detail="horizon_days must be positive")

    start_d = spend_date
    end_d = spend_date + timedelta(days=horizon_days)

    dbp = _default_db_path()
    opening_as_of = start_d - timedelta(days=1)
    opening_balance = compute_opening_balance_cents(as_of=opening_as_of, db_path=dbp)
    entries = expand_calendar(start_d, end_d, db_path=dbp)

    # Deterministic baseline balances and min
    balances_base = compute_balances(opening_balance, entries)
    # Sorted for deterministic min selection
    items = sorted(balances_base.items(), key=lambda kv: kv[0])
    if items:
        min_bal = items[0][1]
        min_date = items[0][0]
        for d, bal in items:
            if bal < min_bal:
                min_bal = bal
                min_date = d
    else:
        min_bal = opening_balance
        min_date = start_d

    # Safety predicate is monotonic in spend amount: new_min = min_bal - x
    def is_safe(x: int) -> bool:
        return (min_bal - int(x)) >= buffer_floor

    # Upper bound: at most the current margin to buffer floor
    upper = max(0, min_bal - buffer_floor)
    max_safe = _binary_search_max_spend(is_safe, 0, upper)

    # Evaluate provided amount
    new_min = min_bal - amount_cents
    # The min date remains the same (all subsequent balances are shifted uniformly)
    new_min_date = min_date

    # Compute tight days after applying spend
    # Shift all balances by -amount_cents from spend_date onward only on dates we have entries
    tight_days: list[dict] = []
    for d, bal in items:
        adj = bal - amount_cents
        if adj <= buffer_floor + tight_thresh:
            tight_days.append({"date": d.isoformat(), "balance_cents": adj})
    # Limit to a reasonable size
    tight_days = sorted(tight_days, key=lambda x: x["date"])[:50]

    # Optional reference blended baseline (does not affect decision)
    blended_ref = None
    if mode.startswith("blended"):
        try:
            txns = _load_transactions_for_stats(dbp, window_days=180)
            mults = compute_weekday_multipliers(txns, window_days=180)
            mu_c, sigma_c = compute_daily_stats(txns, window_days=180)
            blended: dict[str, int] = {}
            for d, bal in items:
                w = d.weekday()
                expected = int(round(mu_c * float(mults[w])))
                blended[d.isoformat()] = bal - expected
            blended_ref = {
                "baseline_blended": blended,
                "params": {
                    "mu_daily_cents": int(mu_c),
                    "sigma_daily_cents": int(sigma_c),
                    "weekday_mult": mults,
                },
            }
        except Exception:
            blended_ref = None

    resp = {
        "input": {
            "date": spend_date.isoformat(),
            "amount_cents": amount_cents,
            "mode": mode,
            "buffer_floor": buffer_floor,
            "horizon": {"start": start_d.isoformat(), "end": end_d.isoformat()},
        },
        "decision": {
            "safe": bool(amount_cents <= max_safe),
            "max_safe_today_cents": int(max_safe),
            "new_min_balance_cents": int(new_min),
            "new_min_balance_date": new_min_date.isoformat() if new_min_date else None,
            "tight_days": tight_days,
            "notes": "Decision compares new_min_balance against buffer_floor; max_safe found via integer binary search.",
        },
        "meta": {
            "opening_balance_cents": opening_balance,
            "baseline_min_balance_cents": int(min_bal),
            "baseline_min_balance_date": min_date.isoformat() if min_date else None,
            "db_path": str(dbp),
        },
    }
    if blended_ref is not None:
        resp["reference_blended"] = blended_ref
    return resp
