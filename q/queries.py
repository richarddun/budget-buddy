from __future__ import annotations

import os
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


def _default_db_path() -> Path:
    env = os.getenv("BUDGET_DB_PATH")
    if env:
        return Path(env)
    return Path("localdb/budget.db")


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _parse_date(s: str) -> date:
    return date.fromisoformat(str(s))


def _resolve_category_id(conn: sqlite3.Connection, *, category_id: Optional[int] = None, category: Optional[str] = None) -> Optional[int]:
    if category_id is not None:
        return int(category_id)
    if category:
        # Try alias table first
        cur = conn.execute(
            "SELECT category_id FROM question_category_alias WHERE LOWER(alias) = LOWER(?) LIMIT 1",
            (category.strip(),),
        )
        row = cur.fetchone()
        if row:
            return int(row["category_id"])
        # Fallback to categories by name exact match (case-insensitive)
        cur = conn.execute(
            "SELECT id FROM categories WHERE LOWER(name) = LOWER(?) LIMIT 1",
            (category.strip(),),
        )
        row = cur.fetchone()
        if row:
            return int(row["id"])
    return None


def monthly_total_by_category(
    start: date,
    end: date,
    *,
    category_id: Optional[int] = None,
    category: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    dbp = db_path or _default_db_path()
    with _connect(dbp) as conn:
        cat_id = _resolve_category_id(conn, category_id=category_id, category=category)
        params: Tuple[Any, ...]
        if cat_id is None:
            # If not resolved, sum all expenses (negative amounts) in window
            sql = (
                "SELECT COALESCE(SUM(amount_cents), 0) AS total, "
                "GROUP_CONCAT(idempotency_key) AS evid FROM transactions "
                "WHERE DATE(posted_at) BETWEEN ? AND ? AND amount_cents < 0"
            )
            params = (start.isoformat(), end.isoformat())
        else:
            sql = (
                "SELECT COALESCE(SUM(amount_cents), 0) AS total, "
                "GROUP_CONCAT(idempotency_key) AS evid FROM transactions "
                "WHERE DATE(posted_at) BETWEEN ? AND ? AND amount_cents < 0 AND category_id = ?"
            )
            params = (start.isoformat(), end.isoformat(), int(cat_id))
        cur = conn.execute(sql, params)
        row = cur.fetchone()
        total = int(row["total"] if row and row["total"] is not None else 0)
        evid = []
        if row and row["evid"]:
            evid = [x for x in str(row["evid"]).split(",") if x]
        return {
            "value_cents": total,
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "method": "sum_expense_transactions_in_window",
            "evidence_ids": evid,
        }


def months_between(start: date, end: date) -> int:
    if end < start:
        return 0
    return (end.year - start.year) * 12 + (end.month - start.month) + 1


def monthly_average_by_category(
    start: date,
    end: date,
    *,
    category_id: Optional[int] = None,
    category: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    total_row = monthly_total_by_category(start, end, category_id=category_id, category=category, db_path=db_path)
    months = max(1, months_between(start, end))
    avg = int(round(total_row["value_cents"] / months))
    return {
        "value_cents": avg,
        "window_start": total_row["window_start"],
        "window_end": total_row["window_end"],
        "method": f"monthly_average_over_{months}_months",
        "evidence_ids": total_row["evidence_ids"],
    }


def summary_income(
    start: date,
    end: date,
    *,
    db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    dbp = db_path or _default_db_path()
    with _connect(dbp) as conn:
        cur = conn.execute(
            """
            SELECT COALESCE(SUM(amount_cents), 0) AS total,
                   GROUP_CONCAT(idempotency_key) AS evid
            FROM transactions
            WHERE DATE(posted_at) BETWEEN ? AND ?
              AND amount_cents > 0
            """,
            (start.isoformat(), end.isoformat()),
        )
        row = cur.fetchone()
        total = int(row["total"] if row and row["total"] is not None else 0)
        evid = []
        if row and row["evid"]:
            evid = [x for x in str(row["evid"]).split(",") if x]
        return {
            "value_cents": total,
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "method": "sum_income_transactions_in_window",
            "evidence_ids": evid,
        }


def active_loans(*, db_path: Optional[Path] = None) -> Dict[str, Any]:
    """Return active loans from commitments where type indicates a loan/debt."""
    dbp = db_path or _default_db_path()
    rows: List[Dict[str, Any]] = []
    evid: List[str] = []
    with _connect(dbp) as conn:
        cur = conn.execute(
            """
            SELECT id, name, amount_cents, due_rule, next_due_date, account_id, type
            FROM commitments
            WHERE LOWER(type) IN ('loan', 'debt', 'credit')
            ORDER BY id
            """
        )
        for r in cur:
            rows.append(
                {
                    "id": int(r["id"]),
                    "name": r["name"],
                    "amount_cents": int(r["amount_cents"]),
                    "due_rule": r["due_rule"],
                    "next_due_date": r["next_due_date"],
                    "account_id": int(r["account_id"]),
                    "type": r["type"],
                }
            )
            evid.append(f"commitment:{int(r['id'])}")
    return {"rows": rows, "method": "commitments_type_filter", "evidence_ids": evid}


def category_breakdown(
    start: date,
    end: date,
    *,
    db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    dbp = db_path or _default_db_path()
    rows: List[Dict[str, Any]] = []
    with _connect(dbp) as conn:
        cur = conn.execute(
            """
            SELECT c.id AS category_id,
                   c.name AS category_name,
                   COALESCE(SUM(t.amount_cents), 0) AS total_cents
            FROM transactions t
            LEFT JOIN categories c ON c.id = t.category_id
            WHERE DATE(t.posted_at) BETWEEN ? AND ? AND t.amount_cents < 0
            GROUP BY c.id, c.name
            ORDER BY total_cents ASC
            """,
            (start.isoformat(), end.isoformat()),
        )
        for r in cur:
            rows.append(
                {
                    "category_id": r["category_id"],
                    "category_name": r["category_name"],
                    "total_cents": int(r["total_cents"]),
                }
            )
    return {
        "rows": rows,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "method": "sum_by_category_expenses",
    }


def supporting_transactions(
    start: date,
    end: date,
    *,
    category_id: Optional[int] = None,
    category: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    dbp = db_path or _default_db_path()
    if page < 1:
        page = 1
    page_size = max(1, min(200, page_size))
    offset = (page - 1) * page_size

    with _connect(dbp) as conn:
        cat_id = _resolve_category_id(conn, category_id=category_id, category=category)
        where = "DATE(posted_at) BETWEEN ? AND ?"
        params: List[Any] = [start.isoformat(), end.isoformat()]
        if cat_id is not None:
            where += " AND category_id = ?"
            params.append(int(cat_id))
        # Count
        cur = conn.execute(f"SELECT COUNT(*) AS n FROM transactions WHERE {where}", params)
        total = int(cur.fetchone()["n"])
        # Page
        cur = conn.execute(
            f"""
            SELECT idempotency_key, posted_at, amount_cents, payee, memo, category_id
            FROM transactions
            WHERE {where}
            ORDER BY DATE(posted_at) ASC, idempotency_key ASC
            LIMIT ? OFFSET ?
            """,
            (*params, page_size, offset),
        )
        rows = [dict(r) | {"amount_cents": int(r["amount_cents"]) if r["amount_cents"] is not None else 0} for r in cur]
        evid = [r["idempotency_key"] for r in rows if r["idempotency_key"]]
        return {
            "rows": rows,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
            },
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "method": "list_transactions_window_filtered",
            "evidence_ids": evid,
        }


def subscriptions(
    start: date,
    end: date,
    *,
    db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Basic subscription approximation using commitments of type 'bill'."""
    dbp = db_path or _default_db_path()
    rows: List[Dict[str, Any]] = []
    evid: List[str] = []
    with _connect(dbp) as conn:
        cur = conn.execute(
            """
            SELECT id, name, amount_cents, due_rule, next_due_date
            FROM commitments
            WHERE LOWER(type) IN ('bill','subscription')
            ORDER BY id
            """
        )
        for r in cur:
            rows.append(
                {
                    "id": int(r["id"]),
                    "name": r["name"],
                    "amount_cents": int(r["amount_cents"]),
                    "due_rule": r["due_rule"],
                    "next_due_date": r["next_due_date"],
                }
            )
            evid.append(f"commitment:{int(r['id'])}")
    return {
        "rows": rows,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "method": "commitments_type_bill_or_subscription",
        "evidence_ids": evid,
    }


def household_fixed_costs(*, db_path: Optional[Path] = None) -> Dict[str, Any]:
    """Sum of fixed costs from commitments where type indicates bill/rent/mortgage."""
    dbp = db_path or _default_db_path()
    with _connect(dbp) as conn:
        cur = conn.execute(
            """
            SELECT COALESCE(SUM(amount_cents), 0) AS total,
                   GROUP_CONCAT(id) AS evid
            FROM commitments
            WHERE LOWER(type) IN ('bill','rent','mortgage','utility')
            """
        )
        row = cur.fetchone()
        total = int(row["total"] if row and row["total"] is not None else 0)
        evid = []
        if row and row["evid"]:
            evid = [f"commitment:{x}" for x in str(row["evid"]).split(",") if x]
        return {
            "value_cents": -abs(total),  # fixed costs as negative amount
            "method": "sum_commitments_fixed_types",
            "evidence_ids": evid,
        }

