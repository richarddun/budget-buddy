import sqlite3
from pathlib import Path
from datetime import datetime
import re
from typing import Optional, Dict, Any, Tuple, List

DB_PATH = Path("payee_db.sqlite")


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = _conn()
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS payee_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern TEXT NOT NULL,
            match_type TEXT NOT NULL CHECK (match_type IN ('exact','icontains','regex')),
            suggested_category TEXT,
            suggested_subcategory TEXT,
            suggested_memo TEXT,
            confidence REAL DEFAULT 0.8,
            hit_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(pattern, match_type)
        )
        """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS local_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ynab_tx_id TEXT,
            date TEXT,
            payee TEXT,
            amount REAL,
            matched_rule_id INTEGER,
            assigned_category TEXT,
            assigned_subcategory TEXT,
            confidence REAL,
            source TEXT DEFAULT 'import',
            notes TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(matched_rule_id) REFERENCES payee_rules(id)
        )
        """
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_local_tx_payee ON local_transactions(payee)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_local_tx_date ON local_transactions(date)")
    conn.commit()
    conn.close()


def upsert_rule(
    pattern: str,
    match_type: str = "icontains",
    suggested_category: Optional[str] = None,
    suggested_subcategory: Optional[str] = None,
    suggested_memo: Optional[str] = None,
    confidence: float = 0.8,
) -> int:
    init_db()
    now = datetime.utcnow().isoformat()
    conn = _conn()
    c = conn.cursor()
    # Try update first
    c.execute(
        """
        UPDATE payee_rules
        SET suggested_category = ?,
            suggested_subcategory = ?,
            suggested_memo = ?,
            confidence = ?,
            updated_at = ?
        WHERE pattern = ? AND match_type = ?
        """,
        (
            suggested_category,
            suggested_subcategory,
            suggested_memo,
            confidence,
            now,
            pattern,
            match_type,
        ),
    )
    if c.rowcount == 0:
        c.execute(
            """
            INSERT INTO payee_rules (
                pattern, match_type, suggested_category, suggested_subcategory, suggested_memo,
                confidence, hit_count, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                pattern,
                match_type,
                suggested_category,
                suggested_subcategory,
                suggested_memo,
                confidence,
                now,
                now,
            ),
        )
    conn.commit()
    # Fetch id
    c.execute(
        "SELECT id FROM payee_rules WHERE pattern = ? AND match_type = ?",
        (pattern, match_type),
    )
    row = c.fetchone()
    conn.close()
    return int(row[0]) if row else -1


def _score_match(raw: str, pattern: str, match_type: str) -> float:
    r = raw.casefold()
    p = pattern.casefold()
    if match_type == "exact":
        return 1.0 if r == p else 0.0
    if match_type == "icontains":
        if p in r:
            # Simple proportional score: longer pattern relative to raw
            return max(0.5, min(0.99, len(p) / max(1, len(r))))
        return 0.0
    if match_type == "regex":
        try:
            if re.search(pattern, raw, re.IGNORECASE):
                # Regex matches get a moderate base score
                return 0.75
        except re.error:
            return 0.0
        return 0.0
    return 0.0


def match_payee(raw_payee: str, threshold: float = 0.6) -> Optional[Dict[str, Any]]:
    init_db()
    conn = _conn()
    c = conn.cursor()
    c.execute("SELECT * FROM payee_rules")
    best: Tuple[float, Optional[sqlite3.Row]] = (0.0, None)
    for row in c.fetchall():
        score = _score_match(raw_payee, row["pattern"], row["match_type"]) * float(row["confidence"] or 0.8)
        if score > best[0]:
            best = (score, row)
    conn.close()
    if best[1] is None or best[0] < threshold:
        return None
    row = best[1]
    return {
        "rule_id": int(row["id"]),
        "pattern": row["pattern"],
        "match_type": row["match_type"],
        "suggested_category": row["suggested_category"],
        "suggested_subcategory": row["suggested_subcategory"],
        "suggested_memo": row["suggested_memo"],
        "confidence": round(best[0], 3),
    }


def record_local_transaction(
    *,
    ynab_tx_id: Optional[str],
    date: str,
    payee: str,
    amount: float,
    matched_rule_id: Optional[int] = None,
    assigned_category: Optional[str] = None,
    assigned_subcategory: Optional[str] = None,
    confidence: Optional[float] = None,
    source: str = "import",
    notes: Optional[str] = None,
) -> int:
    init_db()
    now = datetime.utcnow().isoformat()
    conn = _conn()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO local_transactions (
            ynab_tx_id, date, payee, amount, matched_rule_id, assigned_category, assigned_subcategory,
            confidence, source, notes, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ynab_tx_id,
            date,
            payee,
            amount,
            matched_rule_id,
            assigned_category,
            assigned_subcategory,
            confidence,
            source,
            notes,
            now,
        ),
    )
    tx_id = c.lastrowid
    if matched_rule_id is not None:
        c.execute(
            "UPDATE payee_rules SET hit_count = hit_count + 1, updated_at = ? WHERE id = ?",
            (now, matched_rule_id),
        )
    conn.commit()
    conn.close()
    return int(tx_id)


def record_feedback(
    raw_payee: str,
    chosen_category: Optional[str] = None,
    chosen_subcategory: Optional[str] = None,
    memo: Optional[str] = None,
    generalize: bool = False,
    confidence: float = 0.9,
) -> int:
    """Save feedback by creating/updating a rule (exact or generalized)."""
    pattern = raw_payee.strip()
    match_type = "exact"
    if generalize:
        # crude generalization: remove digits and collapse spaces
        pattern = re.sub(r"\d+", "", pattern)
        pattern = re.sub(r"\s+", " ", pattern).strip()
        match_type = "icontains"
    return upsert_rule(
        pattern=pattern,
        match_type=match_type,
        suggested_category=chosen_category,
        suggested_subcategory=chosen_subcategory,
        suggested_memo=memo,
        confidence=confidence,
    )


def list_unmatched(limit: int = 50) -> List[Dict[str, Any]]:
    init_db()
    conn = _conn()
    c = conn.cursor()
    c.execute(
        """
        SELECT id, date, payee, amount
        FROM local_transactions
        WHERE matched_rule_id IS NULL
        ORDER BY date DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    )
    out = [dict(r) for r in c.fetchall()]
    conn.close()
    return out

