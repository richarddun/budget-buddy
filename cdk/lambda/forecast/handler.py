#!/usr/bin/env python3
"""
Budget Buddy — Forecast Lambda Handler

Computes the calendar forecast: opening balance, daily balances,
entries, and minimum balance over a date range.

Uses the same logic as forecast/calendar.py but adapted for Lambda.

API Gateway routes:
  GET /forecast?start=2026-06-01&end=2026-08-01
  GET /forecast?start=2026-06-01&end=2026-08-01&accounts=1,2
"""

import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Optional, Literal

DB_PATH = os.environ.get('DB_PATH', '/mnt/efs/localdb/budget.db')
logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get('LOG_LEVEL', 'INFO'))


# ── Domain types (ported from forecast/calendar.py) ──────────────

ShiftPolicy = Literal["AS_SCHEDULED", "PREV_BUSINESS_DAY", "NEXT_BUSINESS_DAY"]


@dataclass(frozen=True)
class Entry:
    date: date
    type: Literal["inflow", "commitment", "key_event"]
    name: str
    amount_cents: int
    source_id: int
    shift_applied: bool
    policy: Optional[ShiftPolicy]


def _is_weekend(d: date) -> bool:
    return d.weekday() >= 5


def _prev_business_day(d: date) -> date:
    while _is_weekend(d):
        d = d - timedelta(days=1)
    return d


def _next_business_day(d: date) -> date:
    while _is_weekend(d):
        d = d + timedelta(days=1)
    return d


def _apply_shift(d: date, policy: Optional[ShiftPolicy]) -> tuple[date, bool]:
    """Apply business day shift to a date. Returns (shifted_date, was_shifted)."""
    if policy is None or policy == "AS_SCHEDULED":
        return d, False

    shifted = (
        _prev_business_day(d) if policy == "PREV_BUSINESS_DAY"
        else _next_business_day(d)
    )
    return shifted, shifted != d


# ── Database helpers ─────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _compute_opening_balance_cents(
    conn: sqlite3.Connection,
    as_of: date,
    accounts: Optional[set[int]] = None,
) -> int:
    """Sum of cleared transaction balances up to as_of date."""
    if accounts:
        placeholders = ",".join("?" * len(accounts))
        cur = conn.execute(
            f"""
            SELECT COALESCE(SUM(t.amount_cents), 0) AS balance
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            WHERE a.is_active = 1
              AND t.is_cleared = 1
              AND a.id IN ({placeholders})
              AND DATE(t.posted_at) <= DATE(?)
            """,
            (*sorted(accounts), as_of.isoformat()),
        )
    else:
        cur = conn.execute(
            """
            SELECT COALESCE(SUM(t.amount_cents), 0) AS balance
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            WHERE a.is_active = 1
              AND t.is_cleared = 1
              AND DATE(t.posted_at) <= DATE(?)
            """,
            (as_of.isoformat(),),
        )
    return int(cur.fetchone()["balance"])


def _expand_calendar(
    conn: sqlite3.Connection,
    start: date,
    end: date,
    accounts: Optional[set[int]] = None,
) -> list[Entry]:
    """
    Expand all recurring items (commitments, key events) into individual
    Entry objects within the date range.
    """
    entries: list[Entry] = []

    # ── Commitments ──────────────────────────────────────────────
    cur = conn.execute(
        """
        SELECT c.*, a.name AS account_name
        FROM commitments c
        JOIN accounts a ON a.id = c.account_id
        WHERE a.is_active = 1
          AND c.next_due_date IS NOT NULL
        ORDER BY c.next_due_date ASC
        """
    )
    for row in cur.fetchall():
        amount_cents = int(row["amount_cents"])
        due_rule = str(row["due_rule"]).strip().upper()
        next_due_str = row["next_due_date"]

        if not next_due_str:
            continue

        d = date.fromisoformat(next_due_str)
        source_id = int(row["id"])

        # Skip if past horizon
        if d > end:
            continue

        # Generate occurrences
        while d <= end:
            if d >= start:
                shifted, was_shifted = _apply_shift(d, None)
                entries.append(Entry(
                    date=shifted,
                    type="commitment",
                    name=str(row["name"]),
                    amount_cents=amount_cents,
                    source_id=source_id,
                    shift_applied=was_shifted,
                    policy=None,
                ))

            # Advance to next occurrence
            if due_rule == "MONTHLY":
                # Advance by 1 month
                month = d.month + 1
                year = d.year + (month - 1) // 12
                month = ((month - 1) % 12) + 1
                try:
                    d = d.replace(year=year, month=month)
                except ValueError:
                    # Handle month-end rollover
                    import calendar
                    last_day = calendar.monthrange(year, month)[1]
                    d = d.replace(year=year, month=month, day=min(d.day, last_day))
            elif due_rule == "WEEKLY":
                d += timedelta(days=7)
            elif due_rule == "BIWEEKLY":
                d += timedelta(days=14)
            elif due_rule == "ANNUAL":
                d = d.replace(year=d.year + 1)
            else:
                break  # ONE_OFF or unknown

    # ── Key spend events ─────────────────────────────────────────
    cur = conn.execute(
        """
        SELECT k.*
        FROM key_spend_events k
        WHERE k.event_date IS NOT NULL
        ORDER BY k.event_date ASC
        """
    )
    for row in cur.fetchall():
        event_date_str = row["event_date"]
        if not event_date_str:
            continue

        d = date.fromisoformat(event_date_str)
        repeat = str(row["repeat_rule"] or "ONE_OFF").strip().upper()
        policy = str(row["shift_policy"] or "AS_SCHEDULED").strip().upper()
        shift_policy: ShiftPolicy = policy if policy in ("AS_SCHEDULED", "PREV_BUSINESS_DAY", "NEXT_BUSINESS_DAY") else "AS_SCHEDULED"

        while d <= end:
            if d >= start:
                shifted, was_shifted = _apply_shift(d, shift_policy)
                entries.append(Entry(
                    date=shifted,
                    type="key_event",
                    name=str(row["name"]),
                    amount_cents=int(row["planned_amount_cents"]) if row["planned_amount_cents"] else 0,
                    source_id=int(row["id"]),
                    shift_applied=was_shifted,
                    policy=shift_policy,
                ))

            # Advance
            if repeat == "MONTHLY":
                month = d.month + 1
                year = d.year + (month - 1) // 12
                month = ((month - 1) % 12) + 1
                try:
                    d = d.replace(year=year, month=month)
                except ValueError:
                    import calendar
                    last_day = calendar.monthrange(year, month)[1]
                    d = d.replace(year=year, month=month, day=min(d.day, last_day))
            elif repeat == "WEEKLY":
                d += timedelta(days=7)
            elif repeat == "ANNUAL":
                d = d.replace(year=d.year + 1)
            else:
                break  # ONE_OFF

    # Sort by date
    entries.sort(key=lambda e: (e.date, e.type, e.name))
    return entries


def _compute_balances(
    opening_balance_cents: int,
    entries: list[Entry],
) -> dict[str, int]:
    """Compute daily balances from opening + entries."""
    from collections import defaultdict

    daily_deltas: dict[date, int] = defaultdict(int)
    for e in entries:
        daily_deltas[e.date] += e.amount_cents

    balances: dict[str, int] = {}
    running = opening_balance_cents

    all_dates = sorted(daily_deltas.keys())
    if not all_dates:
        return {}

    for d in all_dates:
        running += daily_deltas[d]
        balances[d.isoformat()] = running

    return balances


# ── Lambda handler ───────────────────────────────────────────────

def handler(event: dict, context: Any) -> dict[str, Any]:
    """
    GET /forecast?start=2026-06-01&end=2026-08-01

    Returns:
      - opening_balance_cents
      - entries (list of forecast entries)
      - balances (date → cents map)
      - min_balance_cents / min_balance_date
    """
    logger.info(f"Forecast handler invoked")

    # Parse query parameters
    params = event.get("queryStringParameters") or {}
    start_str = params.get("start")
    end_str = params.get("end")
    accounts_str = params.get("accounts")

    if not start_str or not end_str:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "start and end query parameters are required (YYYY-MM-DD)"}),
        }

    try:
        start = date.fromisoformat(start_str)
        end = date.fromisoformat(end_str)
    except ValueError as e:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": f"Invalid date format: {e}"}),
        }

    accounts: Optional[set[int]] = None
    if accounts_str:
        try:
            accounts = set(int(x) for x in accounts_str.split(","))
        except ValueError:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "accounts must be comma-separated integers"}),
            }

    conn = _connect()
    try:
        as_of = start - timedelta(days=1)
        opening = _compute_opening_balance_cents(conn, as_of, accounts)
        entries = _expand_calendar(conn, start, end, accounts)
        balances = _compute_balances(opening, entries)

        # Find min balance
        min_balance_cents = None
        min_balance_date = None
        for d_str, bal in balances.items():
            if min_balance_cents is None or bal < min_balance_cents:
                min_balance_cents = bal
                min_balance_date = d_str

        result = {
            "opening_balance_cents": opening,
            "opening_balance_display": f"€{opening/100:,.2f}",
            "horizon": {
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
            "entries": [
                {
                    "date": e.date.isoformat(),
                    "type": e.type,
                    "name": e.name,
                    "amount_cents": e.amount_cents,
                    "amount_display": f"€{e.amount_cents/100:,.2f}",
                }
                for e in entries
            ],
            "balances": balances,
            "min_balance_cents": min_balance_cents,
            "min_balance_date": min_balance_date,
        }

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps(result, default=str),
        }

    except sqlite3.OperationalError as e:
        logger.error(f"Database error: {e}")
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Database error", "detail": str(e)}),
        }
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Internal server error"}),
        }
    finally:
        conn.close()


# ── Local testing ────────────────────────────────────────────────
if __name__ == "__main__":
    # Test: 3-month forecast
    from datetime import date
    today = date.today()
    start = today.isoformat()
    end = (today + timedelta(days=90)).isoformat()

    event = {
        "routeKey": "GET /forecast",
        "rawPath": f"/forecast?start={start}&end={end}",
        "requestContext": {"http": {"method": "GET", "path": "/forecast"}},
        "queryStringParameters": {"start": start, "end": end},
        "pathParameters": {},
        "body": "{}",
    }
    result = handler(event, None)
    output = json.loads(result["body"])
    print(f"Opening: {output['opening_balance_display']}")
    print(f"Entries: {len(output['entries'])}")
    print(f"Min balance: {output['min_balance_cents']}")
    print(f"Min date: {output['min_balance_date']}")
    print(f"Days with balances: {len(output['balances'])}")