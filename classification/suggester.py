from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple


@dataclass(frozen=True)
class Suggestion:
    category_id: Optional[int]
    confidence: float
    notes: str
    category_name: Optional[str] = None


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _find_internal_category_id(conn: sqlite3.Connection, name: str) -> Optional[Tuple[int, str]]:
    cur = conn.execute(
        "SELECT id, name FROM categories WHERE (source IS NULL OR source='internal') AND name = ?",
        (name,),
    )
    row = cur.fetchone()
    if row:
        return int(row["id"]), str(row["name"])  # type: ignore
    return None


def _keyword_guess(conn: sqlite3.Connection, text: str) -> Optional[Tuple[int, str, float, str]]:
    """Very simple keyword-to-category heuristics that map to existing internal categories if present.

    Returns (category_id, category_name, confidence, note) or None.
    """
    text_l = (text or "").lower()
    # Map of keyword -> internal category name
    candidates = [
        ("uber", "Transport"),
        ("lyft", "Transport"),
        ("gas", "Transport"),
        ("fuel", "Transport"),
        ("grocery", "Groceries"),
        ("walmart", "Groceries"),
        ("aldi", "Groceries"),
        ("costco", "Groceries"),
        ("amazon", "Shopping"),
        ("target", "Shopping"),
        ("starbucks", "Coffee"),
        ("coffee", "Coffee"),
        ("netflix", "Subscriptions"),
        ("spotify", "Subscriptions"),
        ("hulu", "Subscriptions"),
        ("rent", "Rent"),
        ("electric", "Utilities"),
        ("water", "Utilities"),
        ("internet", "Utilities"),
        ("insurance", "Insurance"),
        ("gym", "Fitness"),
        ("pharmacy", "Health"),
        ("doctor", "Health"),
    ]
    for kw, cat_name in candidates:
        if kw in text_l:
            found = _find_internal_category_id(conn, cat_name)
            if found:
                cid, cname = found
                return cid, cname, 0.55, f"keyword match '{kw}' -> {cname}"
    return None


def suggest(
    db_path: Path,
    *,
    payee: Optional[str] = None,
    memo: Optional[str] = None,
    csv_category: Optional[str] = None,
) -> Suggestion:
    """Suggest an internal category id for a transaction-like item.

    Heuristics order:
    1) Local payee rules (from localdb.payee_db) → map suggested_subcategory to an internal category id by name.
    2) CSV category name (when present) → internal category by exact name.
    3) Keyword features on payee+memo.

    Never writes to the DB — returns only suggestions.
    """
    payee_s = (payee or "").strip()
    memo_s = (memo or "").strip()

    with _connect(db_path) as conn:
        # 1) Payee rules
        try:
            from localdb import payee_db  # lazy import

            match = payee_db.match_payee(payee_s) if payee_s else None
        except Exception:
            match = None

        if match:
            # Prefer subcategory if provided; fall back to category
            sub = match.get("suggested_subcategory") or match.get("suggested_category")
            if sub:
                found = _find_internal_category_id(conn, str(sub))
                if found:
                    cid, cname = found
                    conf = float(match.get("confidence") or 0.8)
                    return Suggestion(
                        category_id=cid,
                        category_name=cname,
                        confidence=conf,
                        notes=f"payee rule match ({match.get('match_type')}:{match.get('pattern')})",
                    )

        # 2) CSV category name → internal category by exact name
        if csv_category:
            found = _find_internal_category_id(conn, csv_category)
            if found:
                cid, cname = found
                return Suggestion(
                    category_id=cid,
                    category_name=cname,
                    confidence=0.6,
                    notes="csv category name match",
                )

        # 3) Keyword guesses on payee+memo
        guess = _keyword_guess(conn, f"{payee_s} {memo_s}")
        if guess:
            cid, cname, conf, note = guess
            return Suggestion(category_id=cid, category_name=cname, confidence=conf, notes=note)

    return Suggestion(category_id=None, category_name=None, confidence=0.0, notes="no suggestion")


def extract_csv_category(import_meta_json: Optional[str]) -> Optional[str]:
    """Helper to read csv_category from a transactions.import_meta_json blob."""
    if not import_meta_json:
        return None
    try:
        meta = json.loads(import_meta_json)
        v = meta.get("csv_category")
        if isinstance(v, str) and v.strip():
            return v.strip()
        return None
    except Exception:
        return None

