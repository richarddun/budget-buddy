"""Spending Reports API — Monthly bar charts, category breakdown, year-over-year trends.

Endpoints:
  GET /api/reports/monthly-summary        — Monthly spending totals (bar chart data)
  GET /api/reports/category-breakdown     — Spending by category for a given month
  GET /api/reports/year-over-year         — Year-over-year monthly comparison
  GET /api/reports/top-payees             — Top payees by spending (all time or filtered)
  GET /api/reports/dashboard              — Aggregated dashboard data for the template
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from datetime import datetime as _datetime
from collections import defaultdict
import sqlite3

from fastapi import APIRouter, HTTPException, Query, Request

from forecast.calendar import _default_db_path
from security.deps import require_auth, require_csrf, rate_limit


router = APIRouter()


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _current_year_month() -> tuple[int, int]:
    now = _datetime.utcnow()
    return now.year, now.month


def _yyyymm(year: int, month: int) -> int:
    return year * 100 + month


def _month_start_end_iso(year: int, month: int) -> tuple[str, str]:
    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1
    start = f"{year:04d}-{month:02d}-01"
    end = f"{next_year:04d}-{next_month:02d}-01"
    return start, end


def _last_n_months(n: int = 12) -> list[tuple[int, int]]:
    """Return list of (year, month) tuples for the last N months, most recent first."""
    cy, cm = _current_year_month()
    months = []
    for i in range(n):
        m = cm - i
        y = cy
        while m < 1:
            m += 12
            y -= 1
        months.append((y, m))
    return months


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────

@router.get("/api/reports/monthly-summary")
def monthly_summary(
    months: int = Query(12, description="Number of months to include"),
    account_id: Optional[int] = Query(None, description="Filter by account ID"),
):
    """Get monthly spending totals. Returns arrays suitable for bar charts.

    Returns:
      - labels: array of "YYYY-MM" strings
      - income: array of total income in cents per month (positive inflows)
      - spending: array of total spending in cents per month (absolute value of outflows)
      - net: array of net change per month (income - spending)
    """
    dbp = _default_db_path()
    with _connect(dbp) as conn:
        month_list = _last_n_months(months)
        
        labels = []
        income_series = []
        spending_series = []
        net_series = []
        
        for year, month in month_list:
            start, end = _month_start_end_iso(year, month)
            label = f"{year}-{month:02d}"
            labels.append(label)
            
            acct_filter = "AND account_id = ?" if account_id else ""
            params_start_end = [start, end]
            if account_id:
                params_start_end.append(account_id)
            
            # Income (positive amounts)
            income_row = conn.execute(
                f"""
                SELECT COALESCE(SUM(amount_cents), 0) AS total
                FROM transactions
                WHERE amount_cents > 0 AND posted_at >= ? AND posted_at < ?
                {acct_filter}
                """,
                params_start_end,
            ).fetchone()
            income_cents = int(income_row["total"]) if income_row else 0
            
            # Spending (negative amounts, return absolute)
            spend_row = conn.execute(
                f"""
                SELECT COALESCE(SUM(ABS(amount_cents)), 0) AS total
                FROM transactions
                WHERE amount_cents < 0 AND posted_at >= ? AND posted_at < ?
                {acct_filter}
                """,
                params_start_end,
            ).fetchone()
            spending_cents = int(spend_row["total"]) if spend_row else 0
            
            income_series.append(income_cents)
            spending_series.append(spending_cents)
            net_series.append(income_cents - spending_cents)
        
        # Reverse to chronological order (oldest first)
        labels.reverse()
        income_series.reverse()
        spending_series.reverse()
        net_series.reverse()
        
        return {
            "labels": labels,
            "income": income_series,
            "spending": spending_series,
            "net": net_series,
            "currency_symbol": "€",
        }


@router.get("/api/reports/category-breakdown")
def category_breakdown(
    year: Optional[int] = Query(None, description="Year (default: current)"),
    month: Optional[int] = Query(None, description="Month 1-12 (default: current)"),
    min_pct: float = Query(1.0, description="Minimum percentage to include as separate slice"),
):
    """Get spending breakdown by category for a given month.

    Returns each category's spending with percentage and color info.
    Categories below min_pct are grouped into 'Other'.
    """
    cy, cm = _current_year_month()
    year = year if year is not None else cy
    month = month if month is not None else cm
    
    start, end = _month_start_end_iso(year, month)
    
    dbp = _default_db_path()
    with _connect(dbp) as conn:
        rows = conn.execute(
            """
            SELECT 
                COALESCE(c.name, 'Uncategorized') AS category_name,
                c.id AS category_id,
                COALESCE(p.name, '') AS parent_name,
                SUM(ABS(t.amount_cents)) AS total_cents,
                COUNT(*) AS txn_count
            FROM transactions t
            LEFT JOIN categories c ON c.id = t.category_id
            LEFT JOIN categories p ON p.id = c.parent_id
            WHERE t.amount_cents < 0 AND t.posted_at >= ? AND t.posted_at < ?
            GROUP BY t.category_id
            ORDER BY total_cents DESC
            """,
            (start, end),
        ).fetchall()
        
        raw_items = []
        grand_total = 0
        for r in rows:
            total = int(r["total_cents"])
            grand_total += total
            raw_items.append({
                "category_id": r["category_id"],
                "category_name": r["category_name"],
                "parent_name": r["parent_name"],
                "total_cents": total,
                "txn_count": int(r["txn_count"]),
            })
        
        # Group small categories into "Other"
        items = []
        other_cents = 0
        other_count = 0
        for item in raw_items:
            pct = (item["total_cents"] / grand_total * 100) if grand_total > 0 else 0
            if pct >= min_pct:
                item["percentage"] = round(pct, 1)
                items.append(item)
            else:
                other_cents += item["total_cents"]
                other_count += item["txn_count"]
        
        if other_cents > 0:
            items.append({
                "category_id": None,
                "category_name": "Other",
                "parent_name": "",
                "total_cents": other_cents,
                "txn_count": other_count,
                "percentage": round(other_cents / grand_total * 100, 1) if grand_total > 0 else 0,
            })
        
        return {
            "year": year,
            "month": month,
            "label": f"{year}-{month:02d}",
            "grand_total_cents": grand_total,
            "categories": items,
        }


@router.get("/api/reports/year-over-year")
def year_over_year(
    months_back: int = Query(24, description="Number of months to look back for comparison"),
):
    """Year-over-year monthly spending comparison.

    Compares spending in each month against the same month in the previous year.
    Returns only months where data exists in both years.
    """
    dbp = _default_db_path()
    with _connect(dbp) as conn:
        # Get all months with data
        rows = conn.execute(
            """
            SELECT 
                CAST(strftime('%Y', posted_at) AS INTEGER) AS year,
                CAST(strftime('%m', posted_at) AS INTEGER) AS month,
                SUM(ABS(amount_cents)) AS total_cents
            FROM transactions
            WHERE amount_cents < 0
            GROUP BY year, month
            ORDER BY year DESC, month DESC
            LIMIT ?
            """,
            (months_back,),
        ).fetchall()
        
        # Build lookup: (year, month) -> total_cents
        data_by_month: dict[tuple[int, int], int] = {}
        for r in rows:
            data_by_month[(int(r["year"]), int(r["month"]))] = int(r["total_cents"])
        
        # Find pairs (current year, previous year)
        comparisons = []
        for (year, month), current_total in sorted(data_by_month.items()):
            prev_total = data_by_month.get((year - 1, month))
            if prev_total is not None:
                change = current_total - prev_total
                change_pct = round((change / prev_total) * 100, 1) if prev_total > 0 else 0
                comparisons.append({
                    "month": f"{year}-{month:02d}",
                    "month_label": f"{month:02d}/{year}",
                    "current_year": year,
                    "previous_year": year - 1,
                    "current_total_cents": current_total,
                    "previous_total_cents": prev_total,
                    "change_cents": change,
                    "change_percentage": change_pct,
                    "direction": "up" if change > 0 else ("down" if change < 0 else "flat"),
                })
        
        comparisons.sort(key=lambda x: x["month"])
        
        return {
            "comparisons": comparisons,
            "count": len(comparisons),
        }


@router.get("/api/reports/top-payees")
def top_payees(
    limit: int = Query(20, description="Number of top payees to return"),
    months: int = Query(3, description="Look back this many months"),
):
    """Get top payees by total spending."""
    cy, cm = _current_year_month()
    month_list = _last_n_months(months)
    start = f"{month_list[-1][0]:04d}-{month_list[-1][1]:02d}-01"
    
    dbp = _default_db_path()
    with _connect(dbp) as conn:
        rows = conn.execute(
            """
            SELECT 
                COALESCE(payee, 'Unknown') AS payee_name,
                SUM(ABS(amount_cents)) AS total_cents,
                COUNT(*) AS txn_count,
                MAX(posted_at) AS last_seen
            FROM transactions
            WHERE amount_cents < 0 AND posted_at >= ?
            GROUP BY payee
            ORDER BY total_cents DESC
            LIMIT ?
            """,
            (start, limit),
        ).fetchall()
        
        items = []
        for r in rows:
            items.append({
                "payee_name": r["payee_name"],
                "total_cents": int(r["total_cents"]),
                "txn_count": int(r["txn_count"]),
                "last_seen": r["last_seen"],
            })
        
        return {
            "items": items,
            "count": len(items),
            "period_months": months,
        }


@router.get("/api/reports/dashboard")
def reports_dashboard(
    months: int = Query(12, description="Number of months for summary chart"),
    compare_months: int = Query(24, description="Months back for YoY comparison"),
    top_payee_limit: int = Query(10, description="Top payees"),
    top_payee_months: int = Query(3, description="Look back for top payees"),
):
    """Aggregated dashboard — returns all report data in one call for template rendering."""
    summary = monthly_summary(months=months)
    breakdown = category_breakdown()
    yoy = year_over_year(months_back=compare_months)
    payees = top_payees(limit=top_payee_limit, months=top_payee_months)
    
    return {
        "monthly_summary": summary,
        "category_breakdown": breakdown,
        "year_over_year": yoy,
        "top_payees": payees,
    }
