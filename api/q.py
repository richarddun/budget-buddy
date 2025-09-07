from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from q import queries as Q


router = APIRouter()


def _parse_date(s: str) -> date:
    try:
        return date.fromisoformat(str(s))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date format; use YYYY-MM-DD")


@router.get("/api/q/monthly-total-by-category")
def get_monthly_total_by_category(
    start: str = Query(..., description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD"),
    category_id: Optional[int] = Query(None),
    category: Optional[str] = Query(None, description="Alias or category name"),
):
    s = _parse_date(start)
    e = _parse_date(end)
    if e < s:
        raise HTTPException(status_code=400, detail="end must be on or after start")
    return Q.monthly_total_by_category(s, e, category_id=category_id, category=category)


@router.get("/api/q/monthly-average-by-category")
def get_monthly_average_by_category(
    start: str = Query(..., description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD"),
    category_id: Optional[int] = Query(None),
    category: Optional[str] = Query(None, description="Alias or category name"),
):
    s = _parse_date(start)
    e = _parse_date(end)
    if e < s:
        raise HTTPException(status_code=400, detail="end must be on or after start")
    return Q.monthly_average_by_category(s, e, category_id=category_id, category=category)


@router.get("/api/q/active-loans")
def get_active_loans():
    return Q.active_loans()


@router.get("/api/q/summary/income")
def get_summary_income(
    start: str = Query(..., description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD"),
):
    s = _parse_date(start)
    e = _parse_date(end)
    if e < s:
        raise HTTPException(status_code=400, detail="end must be on or after start")
    return Q.summary_income(s, e)


@router.get("/api/q/subscriptions")
def get_subscriptions(
    start: str = Query(..., description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD"),
):
    s = _parse_date(start)
    e = _parse_date(end)
    if e < s:
        raise HTTPException(status_code=400, detail="end must be on or after start")
    return Q.subscriptions(s, e)


@router.get("/api/q/category-breakdown")
def get_category_breakdown(
    start: str = Query(..., description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD"),
):
    s = _parse_date(start)
    e = _parse_date(end)
    if e < s:
        raise HTTPException(status_code=400, detail="end must be on or after start")
    return Q.category_breakdown(s, e)


@router.get("/api/q/supporting-transactions")
def get_supporting_transactions(
    start: str = Query(..., description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD"),
    category_id: Optional[int] = Query(None),
    category: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    s = _parse_date(start)
    e = _parse_date(end)
    if e < s:
        raise HTTPException(status_code=400, detail="end must be on or after start")
    return Q.supporting_transactions(s, e, category_id=category_id, category=category, page=page, page_size=page_size)


@router.get("/api/q/household-fixed-costs")
def get_household_fixed_costs():
    return Q.household_fixed_costs()

