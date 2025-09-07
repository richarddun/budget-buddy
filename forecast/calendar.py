from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, List, Literal, Optional, Tuple


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


def _default_db_path() -> Path:
    # Allow override via env var to support tests
    env = os.getenv("BUDGET_DB_PATH")
    if env:
        return Path(env)
    return Path("localdb/budget.db")


def _is_weekend(d: date) -> bool:
    # Monday = 0 .. Sunday = 6
    return d.weekday() >= 5


def _prev_business_day(d: date) -> date:
    while _is_weekend(d):
        d = d - timedelta(days=1)
    return d


def _next_business_day(d: date) -> date:
    while _is_weekend(d):
        d = d + timedelta(days=1)
    return d


def _apply_shift(d: date, policy: ShiftPolicy | None, *, window_days: Optional[int] = None) -> Tuple[date, bool, Optional[ShiftPolicy]]:
    """Apply shift policy to a date; returns (new_date, shift_applied, used_policy).

    - For AS_SCHEDULED or None: do not change the date.
    - For PREV_BUSINESS_DAY: If `d` is weekend, shift to previous Friday.
      If `window_days` is provided, only shift if within that window.
    - For NEXT_BUSINESS_DAY: If `d` is weekend, shift to following Monday.
      `window_days` is ignored for NEXT.
    """
    if policy is None or policy == "AS_SCHEDULED":
        return d, False, "AS_SCHEDULED"

    if policy == "PREV_BUSINESS_DAY":
        if _is_weekend(d):
            shifted = _prev_business_day(d)
            if window_days is not None:
                if (d - shifted).days <= window_days:
                    return shifted, True, policy
                # Outside window, keep as scheduled
                return d, False, policy
            return shifted, True, policy
        return d, False, policy

    if policy == "NEXT_BUSINESS_DAY":
        if _is_weekend(d):
            shifted = _next_business_day(d)
            return shifted, True, policy
        return d, False, policy

    # Fallback
    return d, False, policy


def _add_months(d: date, months: int) -> date:
    # Simple month add that clamps to last day of month when needed
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    # clamp day
    from calendar import monthrange

    last_day = monthrange(year, month)[1]
    day = min(d.day, last_day)
    return date(year, month, day)


def _recur_dates(start_from: date, end: date, rule: str) -> Iterable[date]:
    rule_norm = (rule or "ONE_OFF").strip().upper()
    d = start_from
    if rule_norm in ("ONE_OFF", "NONE"):
        if d <= end:
            yield d
        return
    if rule_norm == "WEEKLY":
        while d <= end:
            yield d
            d = d + timedelta(days=7)
        return
    if rule_norm == "BIWEEKLY":
        while d <= end:
            yield d
            d = d + timedelta(days=14)
        return
    if rule_norm in ("MONTHLY", "MONTHLY_BY_DATE"):
        while d <= end:
            yield d
            d = _add_months(d, 1)
        return
    if rule_norm in ("ANNUAL", "YEARLY"):
        while d <= end:
            yield d
            d = date(d.year + 1, d.month, d.day)
        return
    # Unknown rule: treat as one-off
    if d <= end:
        yield d


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def expand_calendar(start: date, end: date, *, db_path: Optional[Path] = None) -> List[Entry]:
    """Expand known scheduled items to dated entries between start and end (inclusive).

    Sources:
    - scheduled_inflows: default shift policy = NEXT_BUSINESS_DAY
    - commitments: default shift policy = PREV_BUSINESS_DAY; respects flexible_window_days when shifting earlier
    - key_spend_events: respects per-row shift_policy; defaults to AS_SCHEDULED
    """
    if end < start:
        return []

    dbp = db_path or _default_db_path()
    entries: list[Entry] = []

    with _connect(dbp) as conn:
        # Inflows
        for row in conn.execute(
            """
            SELECT id, name, amount_cents, due_rule, next_due_date
            FROM scheduled_inflows
            """
        ):
            if not row["next_due_date"]:
                continue
            start_from = date.fromisoformat(row["next_due_date"])  # seed
            for due in _recur_dates(max(start, start_from), end, row["due_rule"] or "ONE_OFF"):
                scheduled = due
                shifted_date, shifted, used = _apply_shift(scheduled, "NEXT_BUSINESS_DAY")
                entries.append(
                    Entry(
                        date=shifted_date,
                        type="inflow",
                        name=row["name"],
                        amount_cents=int(row["amount_cents"]),
                        source_id=int(row["id"]),
                        shift_applied=shifted,
                        policy=used,
                    )
                )

        # Commitments
        for row in conn.execute(
            """
            SELECT id, name, amount_cents, due_rule, next_due_date, flexible_window_days
            FROM commitments
            """
        ):
            if not row["next_due_date"]:
                continue
            start_from = date.fromisoformat(row["next_due_date"])  # seed
            window = row["flexible_window_days"]
            window_int = int(window) if window is not None else None
            for due in _recur_dates(max(start, start_from), end, row["due_rule"] or "ONE_OFF"):
                scheduled = due
                shifted_date, shifted, used = _apply_shift(scheduled, "PREV_BUSINESS_DAY", window_days=window_int)
                entries.append(
                    Entry(
                        date=shifted_date,
                        type="commitment",
                        name=row["name"],
                        amount_cents=-abs(int(row["amount_cents"])),
                        source_id=int(row["id"]),
                        shift_applied=shifted,
                        policy=used,
                    )
                )

        # Key spend events
        for row in conn.execute(
            """
            SELECT id, name, event_date, repeat_rule, planned_amount_cents, shift_policy
            FROM key_spend_events
            """
        ):
            if not row["event_date"]:
                continue
            start_from = date.fromisoformat(row["event_date"])  # seed
            policy: ShiftPolicy | None
            if row["shift_policy"]:
                p = str(row["shift_policy"]).strip().upper()
                if p in ("AS_SCHEDULED", "PREV_BUSINESS_DAY", "NEXT_BUSINESS_DAY"):
                    policy = p  # type: ignore
                else:
                    policy = "AS_SCHEDULED"
            else:
                policy = "AS_SCHEDULED"
            amount = int(row["planned_amount_cents"]) if row["planned_amount_cents"] is not None else 0
            for due in _recur_dates(max(start, start_from), end, row["repeat_rule"] or "ONE_OFF"):
                scheduled = due
                shifted_date, shifted, used = _apply_shift(scheduled, policy)
                entries.append(
                    Entry(
                        date=shifted_date,
                        type="key_event",
                        name=row["name"],
                        amount_cents=-abs(amount),
                        source_id=int(row["id"]),
                        shift_applied=shifted,
                        policy=used,
                    )
                )

    # Deterministic ordering: by date, then type, then source_id for stability
    entries.sort(key=lambda e: (e.date, e.type, e.source_id))
    return entries


def compute_balances(opening_balance_cents: int, entries: Iterable[Entry]) -> dict[date, int]:
    """Compute daily balances over the dates present in `entries`.

    - Inflows add to balance; commitments and key events subtract.
    - Returns mapping of date -> end-of-day balance for that date.
    - Deterministic given same input sequence; sorts by date then type/source_id internally.
    """
    items = sorted(entries, key=lambda e: (e.date, e.type, e.source_id))
    balances: dict[date, int] = {}
    running = opening_balance_cents
    current_day: Optional[date] = None
    delta_for_day = 0

    def flush_day(d: date, delta: int, bal: int) -> int:
        new_bal = bal + delta
        balances[d] = new_bal
        return new_bal

    for e in items:
        if current_day is None:
            current_day = e.date
            delta_for_day = 0
        if e.date != current_day:
            running = flush_day(current_day, delta_for_day, running)
            current_day = e.date
            delta_for_day = 0
        # inflow positive; others are already negative
        delta_for_day += e.amount_cents

    if current_day is not None:
        running = flush_day(current_day, delta_for_day, running)

    return balances

