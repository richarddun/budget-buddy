from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import asdict
from datetime import date, datetime, timedelta, time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from forecast.calendar import (
    Entry,
    compute_balances,
    expand_calendar,
    _default_db_path,
)
from api.forecast import compute_opening_balance_cents
try:
    from alerts.engine import run_alert_checks  # type: ignore
except Exception:  # pragma: no cover
    run_alert_checks = None  # type: ignore

logger = logging.getLogger("uvicorn.error")


def _tz_name() -> str:
    return os.getenv("SCHED_TZ") or os.getenv("TZ") or "UTC"


def _today_tz() -> date:
    try:
        # Use zoneinfo if available (Python 3.9+)
        from zoneinfo import ZoneInfo  # type: ignore

        tz = ZoneInfo(_tz_name())
        return datetime.now(tz).date()
    except Exception:
        return datetime.utcnow().date()


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _buffer_floor_cents() -> int:
    try:
        return int(os.getenv("BUFFER_FLOOR_CENTS", "0"))
    except Exception:
        return 0


def _load_key_event_lead_times(conn: sqlite3.Connection) -> Dict[int, Optional[int]]:
    lead: Dict[int, Optional[int]] = {}
    for row in conn.execute(
        "SELECT id, lead_time_days FROM key_spend_events"
    ):
        lead[int(row["id"])] = int(row["lead_time_days"]) if row["lead_time_days"] is not None else None
    return lead


def _compute_digest(
    *,
    today: date,
    start: date,
    end: date,
    opening_balance_cents: int,
    entries: List[Entry],
    balances: Dict[date, int],
    db_path: Path,
) -> Dict[str, Any]:
    threshold = _buffer_floor_cents()

    # Current balance as of today (cleared across active accounts)
    current_balance = compute_opening_balance_cents(as_of=today, db_path=db_path)

    # Safe-to-spend today: end-of-day balance for today minus buffer (floor at 0)
    today_eod = balances.get(today, opening_balance_cents)
    safe_to_spend_today = max(today_eod - threshold, 0)

    # Next cliff: earliest date with balance below threshold
    next_cliff_date = None
    next_cliff_balance = None
    for d in sorted(balances.keys()):
        if d >= today and balances[d] < threshold:
            next_cliff_date = d
            next_cliff_balance = balances[d]
            break

    # Min balance/date across horizon
    min_balance_cents = None
    min_balance_date = None
    if balances:
        for d in sorted(balances.keys()):
            b = balances[d]
            if min_balance_cents is None or b < min_balance_cents:
                min_balance_cents = b
                min_balance_date = d

    # Top commitments in next 14 days
    window_end = today + timedelta(days=14)
    upcoming_commitments = [
        {
            "date": e.date.isoformat(),
            "name": e.name,
            "amount_cents": e.amount_cents,
        }
        for e in entries
        if e.type == "commitment" and today <= e.date <= window_end
    ]
    # Sort by absolute amount desc, then date asc, then name
    upcoming_commitments.sort(key=lambda x: (-abs(x["amount_cents"]), x["date"], x["name"]))
    top_commitments = upcoming_commitments[:5]

    # Upcoming key events within lead window
    upcoming_key_events: List[Dict[str, Any]] = []
    with _connect(db_path) as conn:
        lead_map = _load_key_event_lead_times(conn)
    for e in entries:
        if e.type != "key_event":
            continue
        if e.date < today:
            continue
        lead_days = lead_map.get(e.source_id)
        if lead_days is None:
            continue
        days_until = (e.date - today).days
        if 0 <= days_until <= int(lead_days):
            upcoming_key_events.append(
                {
                    "date": e.date.isoformat(),
                    "days_until": days_until,
                    "name": e.name,
                    "amount_cents": e.amount_cents,
                    "source_id": e.source_id,
                }
            )

    upcoming_key_events.sort(key=lambda x: (x["date"], -abs(x["amount_cents"]), x["name"]))

    return {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "horizon": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "days": (end - start).days,
        },
        "balances": {
            "today_balance_cents": today_eod,
            "min_balance_cents": min_balance_cents,
            "min_balance_date": min_balance_date.isoformat() if min_balance_date else None,
            "next_cliff_date": next_cliff_date.isoformat() if next_cliff_date else None,
            "next_cliff_balance_cents": next_cliff_balance,
            "buffer_floor_cents": threshold,
        },
        "current_balance_cents": current_balance,
        "safe_to_spend_today_cents": safe_to_spend_today,
        "top_commitments_next_14_days": top_commitments,
        "upcoming_key_events": upcoming_key_events,
        "meta": {
            "opening_balance_strategy": "sum_cleared_active_accounts_as_of(start_minus_one)",
            "db_path": str(db_path),
            "tz": _tz_name(),
        },
    }


def run_nightly_snapshot(horizon_days: int = 120, *, db_path: Optional[Path] = None) -> Dict[str, Any]:
    """Compute forecast snapshot and persist to forecast_snapshot.

    Returns the computed digest payload for convenience.
    """
    dbp = db_path or _default_db_path()
    today = _today_tz()
    start = today
    end = start + timedelta(days=horizon_days)

    # Opening balance as of the day before horizon start
    opening_as_of = start - timedelta(days=1)
    opening_balance = compute_opening_balance_cents(as_of=opening_as_of, db_path=dbp)

    # Expand calendar and compute balances
    entries = expand_calendar(start, end, db_path=dbp)
    balances = compute_balances(opening_balance, entries)

    # Build snapshot payload (deterministic)
    payload = {
        "opening_balance_cents": opening_balance,
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
        "balances": {d.isoformat(): bal for d, bal in balances.items()},
        "meta": {
            "horizon": {"start": start.isoformat(), "end": end.isoformat()},
            "db_path": str(dbp),
        },
    }

    # Min balance/date
    min_balance_cents = None
    min_balance_date = None
    for d in sorted(balances.keys()):
        b = balances[d]
        if min_balance_cents is None or b < min_balance_cents:
            min_balance_cents = b
            min_balance_date = d

    # Persist snapshot row
    created_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    with _connect(dbp) as conn:
        conn.execute(
            """
            INSERT INTO forecast_snapshot(created_at, horizon_start, horizon_end, json_payload, min_balance_cents, min_balance_date)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                start.isoformat(),
                end.isoformat(),
                json.dumps(payload, separators=(",", ":")),
                int(min_balance_cents) if min_balance_cents is not None else None,
                min_balance_date.isoformat() if min_balance_date else None,
            ),
        )
        conn.commit()

    # Compute digest last to reuse computed data
    digest = _compute_digest(
        today=today,
        start=start,
        end=end,
        opening_balance_cents=opening_balance,
        entries=entries,
        balances=balances,
        db_path=dbp,
    )

    # Run alert checks (thresholds etc.) after new snapshot is stored
    try:
        if run_alert_checks is not None:
            run_alert_checks(db_path=dbp)
    except Exception as e:  # pragma: no cover
        logger.exception(f"Alert checks failed: {e}")

    logger.info(
        f"[SNAPSHOT] New forecast snapshot at {created_at} for {start.isoformat()}..{end.isoformat()}"
    )
    return digest


async def run_nightly_snapshot_async(horizon_days: int = 120, *, db_path: Optional[Path] = None) -> Dict[str, Any]:
    # Thin async shim for scheduler compatibility
    return run_nightly_snapshot(horizon_days=horizon_days, db_path=db_path)
