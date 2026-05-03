from __future__ import annotations

from pathlib import Path
from typing import Optional
import sqlite3

from fastapi import APIRouter, HTTPException, Query, Request

from forecast.calendar import _default_db_path
from security.deps import require_auth, require_csrf, rate_limit


router = APIRouter()


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


@router.get("/api/transactions/{idempotency_key}/splits")
def list_splits(idempotency_key: str):
    """List all splits for a transaction."""
    dbp = _default_db_path()
    with _connect(dbp) as conn:
        # Verify transaction exists
        txn = conn.execute(
            "SELECT idempotency_key, amount_cents, payee FROM transactions WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if not txn:
            raise HTTPException(status_code=404, detail="Transaction not found")

        splits = conn.execute(
            """
            SELECT ts.id, ts.idempotency_key, ts.category_id, ts.amount_cents, ts.memo, ts.created_at,
                   c.name AS category_name
            FROM transaction_splits ts
            LEFT JOIN categories c ON c.id = ts.category_id
            WHERE ts.idempotency_key = ?
            ORDER BY ts.id
            """,
            (idempotency_key,),
        ).fetchall()

        total_split = sum(int(r["amount_cents"]) for r in splits)

        return {
            "transaction": {
                "idempotency_key": txn["idempotency_key"],
                "amount_cents": int(txn["amount_cents"]),
                "payee": txn["payee"],
            },
            "splits": [
                {
                    "id": int(r["id"]),
                    "category_id": int(r["category_id"]) if r["category_id"] is not None else None,
                    "category_name": r["category_name"],
                    "amount_cents": int(r["amount_cents"]),
                    "memo": r["memo"],
                    "created_at": r["created_at"],
                }
                for r in splits
            ],
            "total_split_cents": total_split,
            "remaining_cents": abs(int(txn["amount_cents"])) - total_split,
        }


@router.post("/api/transactions/{idempotency_key}/splits")
async def create_split(idempotency_key: str, request: Request):
    """Add a split to a transaction.

    Body (JSON):
    - category_id: int (required)
    - amount_cents: int (required, positive)
    - memo: str | None (optional)
    """
    require_auth(request)
    require_csrf(request)
    rate_limit(request, scope="split-create", limit=60, window_s=60)

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    category_id = payload.get("category_id")
    if category_id is None:
        raise HTTPException(status_code=400, detail="'category_id' is required")
    try:
        category_id = int(category_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="'category_id' must be an integer")

    amount_cents = payload.get("amount_cents")
    if amount_cents is None:
        raise HTTPException(status_code=400, detail="'amount_cents' is required")
    try:
        amount_cents = int(amount_cents)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="'amount_cents' must be an integer")
    if amount_cents <= 0:
        raise HTTPException(status_code=400, detail="'amount_cents' must be positive")

    memo = (payload.get("memo") or "").strip() or None

    dbp = _default_db_path()
    with _connect(dbp) as conn:
        # Verify transaction exists
        txn = conn.execute(
            "SELECT idempotency_key, amount_cents FROM transactions WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if not txn:
            raise HTTPException(status_code=404, detail="Transaction not found")

        # Verify category exists
        cat = conn.execute(
            "SELECT id FROM categories WHERE id = ? AND is_archived = 0",
            (category_id,),
        ).fetchone()
        if not cat:
            raise HTTPException(status_code=404, detail="Category not found or archived")

        # Check that total split doesn't exceed transaction amount
        existing_total = conn.execute(
            "SELECT COALESCE(SUM(amount_cents), 0) AS total FROM transaction_splits WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()[0]
        txn_amount = abs(int(txn["amount_cents"]))

        if existing_total + amount_cents > txn_amount:
            raise HTTPException(
                status_code=400,
                detail=f"Split total (€{(existing_total + amount_cents)/100:.2f}) would exceed transaction amount (€{txn_amount/100:.2f})",
            )

        conn.execute(
            """
            INSERT INTO transaction_splits(idempotency_key, category_id, amount_cents, memo)
            VALUES (?, ?, ?, ?)
            """,
            (idempotency_key, category_id, amount_cents, memo),
        )
        conn.commit()

        new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    return {
        "status": "ok",
        "id": int(new_id),
        "idempotency_key": idempotency_key,
        "category_id": category_id,
        "amount_cents": amount_cents,
        "memo": memo,
    }


@router.delete("/api/transactions/{idempotency_key}/splits/{split_id}")
async def delete_split(idempotency_key: str, split_id: int, request: Request):
    """Delete a split from a transaction."""
    require_auth(request)
    require_csrf(request)
    rate_limit(request, scope="split-delete", limit=60, window_s=60)

    dbp = _default_db_path()
    with _connect(dbp) as conn:
        split = conn.execute(
            "SELECT id FROM transaction_splits WHERE id = ? AND idempotency_key = ?",
            (split_id, idempotency_key),
        ).fetchone()
        if not split:
            raise HTTPException(status_code=404, detail="Split not found")

        conn.execute("DELETE FROM transaction_splits WHERE id = ?", (split_id,))
        conn.commit()

    return {"status": "ok", "deleted_id": split_id}


@router.put("/api/transactions/{idempotency_key}/splits/{split_id}")
async def update_split(idempotency_key: str, split_id: int, request: Request):
    """Update a split's category, amount, or memo.

    Body (JSON, all optional):
    - category_id: int | None
    - amount_cents: int | None (positive)
    - memo: str | None
    """
    require_auth(request)
    require_csrf(request)
    rate_limit(request, scope="split-update", limit=60, window_s=60)

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    dbp = _default_db_path()
    with _connect(dbp) as conn:
        split = conn.execute(
            "SELECT id, idempotency_key, category_id, amount_cents, memo FROM transaction_splits WHERE id = ? AND idempotency_key = ?",
            (split_id, idempotency_key),
        ).fetchone()
        if not split:
            raise HTTPException(status_code=404, detail="Split not found")

        new_category_id = split["category_id"]
        new_amount_cents = int(split["amount_cents"])
        new_memo = split["memo"]

        if "category_id" in payload:
            val = payload["category_id"]
            if val is not None:
                try:
                    val = int(val)
                except (ValueError, TypeError):
                    raise HTTPException(status_code=400, detail="'category_id' must be an integer or null")
                cat = conn.execute(
                    "SELECT id FROM categories WHERE id = ? AND is_archived = 0",
                    (val,),
                ).fetchone()
                if not cat:
                    raise HTTPException(status_code=404, detail="Category not found or archived")
            new_category_id = val

        if "amount_cents" in payload:
            val = payload["amount_cents"]
            if val is None:
                raise HTTPException(status_code=400, detail="'amount_cents' cannot be null")
            try:
                val = int(val)
            except (ValueError, TypeError):
                raise HTTPException(status_code=400, detail="'amount_cents' must be an integer")
            if val <= 0:
                raise HTTPException(status_code=400, detail="'amount_cents' must be positive")
            new_amount_cents = val

        if "memo" in payload:
            new_memo = (payload["memo"] or "").strip() or None

        # Validate total doesn't exceed transaction (excluding current split)
        txn = conn.execute(
            "SELECT amount_cents FROM transactions WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        txn_amount = abs(int(txn["amount_cents"]))
        other_total = conn.execute(
            "SELECT COALESCE(SUM(amount_cents), 0) FROM transaction_splits WHERE idempotency_key = ? AND id != ?",
            (idempotency_key, split_id),
        ).fetchone()[0]

        if other_total + new_amount_cents > txn_amount:
            raise HTTPException(
                status_code=400,
                detail=f"Updated split total would exceed transaction amount (€{txn_amount/100:.2f})",
            )

        conn.execute(
            "UPDATE transaction_splits SET category_id = ?, amount_cents = ?, memo = ? WHERE id = ?",
            (new_category_id, new_amount_cents, new_memo, split_id),
        )
        conn.commit()

    return {
        "status": "ok",
        "id": split_id,
        "category_id": new_category_id,
        "amount_cents": new_amount_cents,
        "memo": new_memo,
    }
