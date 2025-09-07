from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from q import queries as Q
from api.forecast import compute_opening_balance_cents  # reuse opening balance helper


# ---- Period helpers ----

def _today() -> date:
    try:
        from zoneinfo import ZoneInfo  # type: ignore
        import os

        tz = ZoneInfo(os.getenv("SCHED_TZ") or os.getenv("TZ") or "UTC")
        return datetime.now(tz).date()
    except Exception:
        return datetime.utcnow().date()


def last_full_months(n: int, *, today: Optional[date] = None) -> Tuple[date, date]:
    """Return start/end covering the last n full calendar months (inclusive)."""
    t = today or _today()
    # Move to the last day of previous month
    first_of_month = t.replace(day=1)
    end = first_of_month - timedelta(days=1)
    # Compute start n-1 months before end's first-day
    y, m = end.year, end.month
    m_start = m - (n - 1)
    y_start = y
    while m_start <= 0:
        m_start += 12
        y_start -= 1
    start = date(y_start, m_start, 1)
    return start, end


def parse_period_token(token: Optional[str]) -> Tuple[date, date, str]:
    """Parse a simple period token into a [start, end] window.

    Supported tokens:
    - '3m_full' (default): last 3 full calendar months
    - 'Xm' : last X months window ending today (inclusive)
    - 'Xd' : last X days window ending today (inclusive)
    """
    if not token or token.strip().lower() in ("3m_full", "loan_default"):
        s, e = last_full_months(3)
        return s, e, "3m_full"
    t = token.strip().lower()
    today = _today()
    if t.endswith("m") and t[:-1].isdigit():
        months = max(1, int(t[:-1]))
        # Start = first day of month (months-1 before current month), end = today
        y, m = today.year, today.month
        m_start = m - (months - 1)
        y_start = y
        while m_start <= 0:
            m_start += 12
            y_start -= 1
        return date(y_start, m_start, 1), today, t
    if t.endswith("d") and t[:-1].isdigit():
        days = max(1, int(t[:-1]))
        start = today - timedelta(days=days - 1)
        return start, today, t
    # Fallback: 3 full months
    s, e = last_full_months(3)
    return s, e, "3m_full"


# ---- Computations used by packs ----

def _sum_subscription_amounts(rows: List[Dict[str, Any]]) -> int:
    total = 0
    for r in rows:
        try:
            total += int(r.get("amount_cents", 0))
        except Exception:
            continue
    return -abs(total) if total > 0 else int(total)


def _stddev(values: List[int]) -> float:
    n = len(values)
    if n <= 1:
        return 0.0
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return var ** 0.5


def _monthly_expense_totals(start: date, end: date) -> Tuple[List[int], List[str]]:
    """Compute per-month absolute expense totals across [start..end].

    Returns (totals_in_cents_positive, evidence_ids)
    """
    # Build a list of month windows
    months: List[Tuple[date, date]] = []
    y, m = start.year, start.month
    cur = date(y, m, 1)
    while cur <= end:
        # Determine end of this month
        if cur.month == 12:
            next_month = date(cur.year + 1, 1, 1)
        else:
            next_month = date(cur.year, cur.month + 1, 1)
        month_end = min(end, next_month - timedelta(days=1))
        months.append((cur, month_end))
        cur = next_month

    totals: List[int] = []
    evid: List[str] = []
    for s, e in months:
        r = Q.monthly_total_by_category(s, e)
        totals.append(abs(int(r.get("value_cents", 0))))
        evid.extend(r.get("evidence_ids", []) or [])
    return totals, evid


def _min_cleared_balance_last_days(days: int) -> Dict[str, Any]:
    """Compute min cleared balance over the last `days` days using transactions only.

    Returns a dict with value_cents (min bal), window_start/end, method, evidence_ids.
    """
    today = _today()
    start = today - timedelta(days=days - 1)
    # Opening balance as of the day before window
    opening_as_of = start - timedelta(days=1)
    opening = compute_opening_balance_cents(as_of=opening_as_of)

    # Load daily sums from transactions in window
    import sqlite3
    from forecast.calendar import _default_db_path

    dbp = _default_db_path()
    evid: List[str] = []
    daily: Dict[date, int] = {}
    with sqlite3.connect(dbp) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """
            SELECT DATE(posted_at) AS d, COALESCE(SUM(amount_cents),0) AS s,
                   GROUP_CONCAT(idempotency_key) AS evid
            FROM transactions
            WHERE DATE(posted_at) BETWEEN ? AND ? AND is_cleared = 1
            GROUP BY DATE(posted_at)
            ORDER BY DATE(posted_at) ASC
            """,
            (start.isoformat(), today.isoformat()),
        )
        for r in cur:
            d = date.fromisoformat(r["d"])
            daily[d] = int(r["s"]) if r["s"] is not None else 0
            if r["evid"]:
                evid.extend([x for x in str(r["evid"]).split(",") if x])

    # Walk the window day-by-day to compute balances
    min_bal = None
    cur_bal = opening
    cur_day = start
    while cur_day <= today:
        cur_bal += daily.get(cur_day, 0)
        if min_bal is None or cur_bal < min_bal:
            min_bal = cur_bal
        cur_day += timedelta(days=1)

    return {
        "value_cents": int(min_bal if min_bal is not None else opening),
        "window_start": start.isoformat(),
        "window_end": today.isoformat(),
        "method": f"min_cleared_balance_from_transactions_last_{days}_days",
        "evidence_ids": evid,
    }


# ---- Pack assembly ----

def assemble_pack(pack: str, period: Optional[str] = None) -> Dict[str, Any]:
    key = pack.strip().lower().replace(" ", "-")

    if key in ("loan", "loan-basics", "loan_application_basics", "loan-application-basics"):
        return _assemble_loan_application_basics(period)
    if key in ("affordability", "affordability-snapshot", "affordability_snapshot"):
        return _assemble_affordability_snapshot(period)

    return {
        "pack": key,
        "error": "unknown_pack",
    }


def _assemble_loan_application_basics(period: Optional[str]) -> Dict[str, Any]:
    # Income over last 3 full months regardless of provided period, per spec
    inc_s, inc_e, inc_token = parse_period_token("3m_full")

    # Category averages over 3 months
    def avg3(alias: str) -> Dict[str, Any]:
        return Q.monthly_average_by_category(inc_s, inc_e, category=alias)

    income = Q.summary_income(inc_s, inc_e)
    loans = Q.active_loans()
    housing = avg3("housing")
    utilities = avg3("utilities")
    childcare = avg3("childcare")
    transport = avg3("transport")
    discretionary = avg3("discretionary")

    # Subscriptions: list + monthly total (sum of commitment amounts)
    # We still include window for consistency (3m_full), though commitments are static
    subs_rows = Q.subscriptions(inc_s, inc_e)
    subs_total = _sum_subscription_amounts(subs_rows.get("rows", []))
    subscriptions = {
        "value_cents": int(subs_total),
        "window_start": inc_s.isoformat(),
        "window_end": inc_e.isoformat(),
        "method": "sum_commitments_subscriptions",
        "evidence_ids": subs_rows.get("evidence_ids", []),
        "rows": subs_rows.get("rows", []),
    }

    return {
        "pack": "loan_application_basics",
        "period": inc_token,
        "sections": [
            {
                "id": "income",
                "title": "Income (last 3 full months)",
                "items": [income],
            },
            {
                "id": "active_loans",
                "title": "Active Loans",
                "items": [loans],
            },
            {
                "id": "housing_cost",
                "title": "Housing Cost (avg 3m)",
                "items": [housing],
            },
            {
                "id": "utilities",
                "title": "Utilities (avg 3m)",
                "items": [utilities],
            },
            {
                "id": "childcare",
                "title": "Childcare (avg 3m)",
                "items": [childcare],
            },
            {
                "id": "transport",
                "title": "Transport (avg 3m)",
                "items": [transport],
            },
            {
                "id": "subscriptions",
                "title": "Subscriptions (monthly total)",
                "items": [subscriptions],
            },
            {
                "id": "discretionary",
                "title": "Discretionary (avg 3m)",
                "items": [discretionary],
            },
        ],
    }


def _assemble_affordability_snapshot(period: Optional[str]) -> Dict[str, Any]:
    # Use provided period when available; default to last 3 full months
    s, e, token = parse_period_token(period or "3m_full")

    income = Q.summary_income(s, e)
    fixed = Q.household_fixed_costs()
    net_after_fixed = int(income.get("value_cents", 0)) + int(fixed.get("value_cents", 0))

    # Monthly volatility (std dev) across monthly absolute expense totals in window
    totals, evid = _monthly_expense_totals(s, e)
    vol = int(round(_stddev(totals)))
    volatility = {
        "value_cents": vol,
        "window_start": s.isoformat(),
        "window_end": e.isoformat(),
        "method": "stddev_monthly_expense_totals",
        "evidence_ids": evid,
    }

    # Min buffer (min cleared balance) over last 60 days
    min_buf = _min_cleared_balance_last_days(60)

    return {
        "pack": "affordability_snapshot",
        "period": token,
        "sections": [
            {
                "id": "net_vs_fixed",
                "title": "Net Income vs Fixed Costs",
                "items": [
                    income,
                    fixed,
                    {
                        "value_cents": net_after_fixed,
                        "window_start": s.isoformat(),
                        "window_end": e.isoformat(),
                        "method": "sum(income, fixed_costs)",
                        "evidence_ids": list((income.get("evidence_ids") or [])) + list((fixed.get("evidence_ids") or [])),
                        "label": "net_after_fixed_cents",
                    },
                ],
            },
            {
                "id": "volatility",
                "title": "Monthly Volatility (std dev)",
                "items": [volatility],
            },
            {
                "id": "min_buffer",
                "title": "Min Cleared Balance (last 60 days)",
                "items": [min_buf],
            },
        ],
    }

