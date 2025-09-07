from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body

from classification.suggester import suggest, extract_csv_category


router = APIRouter()


def _default_db_path() -> Path:
    env = os.getenv("BUDGET_DB_PATH")
    return Path(env) if env else Path("localdb/budget.db")


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_holding_category(conn: sqlite3.Connection) -> int:
    cur = conn.execute(
        "SELECT id FROM categories WHERE (source IS NULL OR source='internal') AND name = ?",
        ("Holding",),
    )
    row = cur.fetchone()
    if row:
        return int(row[0])
    cur = conn.execute(
        "INSERT INTO categories(name, parent_id, is_archived, source, external_id) VALUES(?, NULL, 0, 'internal', NULL)",
        ("Holding",),
    )
    return int(cur.lastrowid)


@router.get("/api/classify/unmapped")
def list_unmapped(limit: int = 50) -> Dict[str, Any]:
    """Return recent transactions mapped to Holding with a suggestion candidate.

    Focus on CSV-imported transactions (source='ynab-csv') for actionable mapping via category_map.
    """
    dbp = _default_db_path()
    out: List[Dict[str, Any]] = []
    with _connect(dbp) as conn:
        holding_id = _ensure_holding_category(conn)
        cur = conn.execute(
            """
            SELECT idempotency_key, posted_at, payee, memo, source, import_meta_json
            FROM transactions
            WHERE category_id = ?
            ORDER BY posted_at DESC
            LIMIT ?
            """,
            (holding_id, int(limit)),
        )
        for r in cur.fetchall():
            csv_cat = extract_csv_category(r["import_meta_json"]) if r["source"] == "ynab-csv" else None
            s = suggest(dbp, payee=r["payee"], memo=r["memo"], csv_category=csv_cat)
            out.append(
                {
                    "idempotency_key": r["idempotency_key"],
                    "posted_at": r["posted_at"],
                    "payee": r["payee"],
                    "memo": r["memo"],
                    "source": r["source"],
                    "csv_category": csv_cat,
                    "suggested_category_id": s.category_id,
                    "suggested_category_name": s.category_name,
                    "confidence": s.confidence,
                    "notes": s.notes,
                }
            )
    return {"count": len(out), "items": out}


@router.get("/api/classify/suggest")
def get_suggestion(payee: Optional[str] = None, memo: Optional[str] = None, csv_category: Optional[str] = None) -> Dict[str, Any]:
    s = suggest(_default_db_path(), payee=payee, memo=memo, csv_category=csv_category)
    return {
        "suggested_category_id": s.category_id,
        "suggested_category_name": s.category_name,
        "confidence": s.confidence,
        "notes": s.notes,
    }


def _upsert_category_map(conn: sqlite3.Connection, *, source: str, external_id: str, internal_category_id: int) -> None:
    # Update if exists
    cur = conn.execute(
        "SELECT internal_category_id FROM category_map WHERE source = ? AND external_id = ?",
        (source, external_id),
    )
    row = cur.fetchone()
    if row:
        if int(row[0]) != internal_category_id:
            conn.execute(
                "UPDATE category_map SET internal_category_id = ? WHERE source = ? AND external_id = ?",
                (internal_category_id, source, external_id),
            )
        return
    conn.execute(
        "INSERT INTO category_map(source, external_id, internal_category_id) VALUES(?,?,?)",
        (source, external_id, internal_category_id),
    )


@router.post("/api/classify/accept")
def accept_suggestion(
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Accept a suggestion and persist mapping or feedback.

    Accepts either:
    - {"mapping_source":"ynab-csv", "external_id":"Groceries", "internal_category_id":123}
      → writes/updates category_map
    - {"payee":"STARBUCKS", "internal_category_name":"Coffee", "generalize":true}
      → writes/updates a payee rule in localdb(payee_db)
    """
    dbp = _default_db_path()
    mapping_source = payload.get("mapping_source")
    external_id = payload.get("external_id")
    internal_category_id = payload.get("internal_category_id")
    payee = payload.get("payee")
    internal_category_name = payload.get("internal_category_name")
    generalize = bool(payload.get("generalize", False))

    if mapping_source and external_id and isinstance(internal_category_id, int):
        with _connect(dbp) as conn:
            # Validate internal category exists
            cur = conn.execute("SELECT name FROM categories WHERE id = ?", (internal_category_id,))
            row = cur.fetchone()
            if not row:
                return {"ok": False, "error": "internal_category_id not found"}
            _upsert_category_map(
                conn,
                source=str(mapping_source),
                external_id=str(external_id),
                internal_category_id=int(internal_category_id),
            )
            conn.commit()
        return {"ok": True, "mode": "category_map", "source": mapping_source, "external_id": external_id}

    if payee and internal_category_name:
        # Record feedback as a payee rule (never mutates budget DB)
        try:
            from localdb import payee_db

            rule_id = payee_db.record_feedback(
                raw_payee=str(payee),
                chosen_category=None,  # group name not known
                chosen_subcategory=str(internal_category_name),
                memo=None,
                generalize=bool(generalize),
                confidence=0.9,
            )
            return {"ok": True, "mode": "payee_rule", "rule_id": int(rule_id)}
        except Exception as e:
            return {"ok": False, "error": f"failed to write payee rule: {e}"}

    return {"ok": False, "error": "invalid payload"}

