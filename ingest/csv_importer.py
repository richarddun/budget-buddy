from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Any, Dict

from db.migrate import run_migrations


@dataclass
class CsvImportResult:
    started_at: str
    finished_at: str
    rows_upserted: int
    status: str
    notes: str


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _ensure_holding_category(conn: sqlite3.Connection) -> int:
    cur = conn.execute(
        "SELECT id FROM categories WHERE (source IS NULL OR source = 'internal') AND name = ?",
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


def _upsert_account(conn: sqlite3.Connection, *, name: str, type_: str, currency: str) -> int:
    cur = conn.execute(
        "SELECT id FROM accounts WHERE name = ? AND type = ? AND currency = ?",
        (name, type_, currency),
    )
    row = cur.fetchone()
    if row:
        return int(row[0])
    cur = conn.execute(
        "INSERT INTO accounts(name, type, currency, is_active) VALUES(?, ?, ?, 1)",
        (name, type_, currency),
    )
    return int(cur.lastrowid)


def _lookup_category_map(conn: sqlite3.Connection, *, source: str, external_id: str) -> Optional[int]:
    cur = conn.execute(
        "SELECT internal_category_id FROM category_map WHERE source = ? AND external_id = ?",
        (source, external_id),
    )
    row = cur.fetchone()
    return int(row[0]) if row else None


def _parse_amount(row: Dict[str, str]) -> int:
    def _num(s: Optional[str]) -> float:
        if not s:
            return 0.0
        s2 = s.strip().replace(",", "")
        # Handle parentheses as negative
        neg = s2.startswith("(") and s2.endswith(")")
        s2 = s2.replace("$", "").replace("€", "").replace("£", "").replace("(", "").replace(")", "")
        try:
            val = float(s2)
            return -val if neg else val
        except Exception:
            return 0.0

    # Prefer unified amount if present
    for key in ("amount", "total", "value"):
        if key in row and str(row[key]).strip() != "":
            return int(round(_num(row[key]) * 100))

    inflow = _num(row.get("inflow"))
    outflow = _num(row.get("outflow"))
    amount = inflow - outflow
    return int(round(amount * 100))


def _parse_date(s: str) -> str:
    s = (s or "").strip()
    # Try common formats
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except Exception:
            continue
    # Fallback to fromisoformat
    try:
        return datetime.fromisoformat(s).date().isoformat()
    except Exception:
        return datetime.utcnow().date().isoformat()


def _norm(s: Any) -> str:
    return " ".join(str(s or "").split()).strip().lower()


def _cleared_flag(v: Any) -> int:
    s = _norm(v)
    return 1 if s in {"cleared", "reconciled", "true", "1", "yes", "y"} else 0


def _build_idem(prefix: str, *, date_iso: str, account_name: str, amount_cents: int, payee: str, memo: str, category: str) -> str:
    canon = "|".join(
        [
            date_iso,
            _norm(account_name),
            str(amount_cents),
            _norm(payee),
            _norm(memo),
            _norm(category),
        ]
    )
    h = hashlib.sha256(canon.encode("utf-8")).hexdigest()
    return f"{prefix}:{h}"


def run_import(db_path: Path, csv_path: Path, *, account_override: Optional[str] = None) -> CsvImportResult:
    """Parse and upsert transactions from a YNAB-exported CSV file.

    - Maps columns (date, payee, memo, amount/outflow+inflow, account, category)
    - Normalizes dates to ISO and amounts to integer cents
    - Builds deterministic idempotency key from canonical row fields
    - Resolves category via category_map(source='ynab-csv', external_id=category_name) if present; else Holding
    - Writes ingest_audit row
    """

    run_migrations(db_path)

    started_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    rows_upserted = 0
    status = "success"
    notes: Dict[str, Any] = {"mode": "csv", "path": str(csv_path)}

    with _connect(db_path) as conn:
        # Pre-insert audit row (running)
        cur = conn.execute(
            "INSERT INTO ingest_audit(source, run_started_at, status, notes) VALUES(?, ?, ?, ?)",
            ("ynab-csv", started_at, "running", json.dumps(notes)),
        )
        audit_id = int(cur.lastrowid)

        holding_id = _ensure_holding_category(conn)

        upsert_sql = (
            """
            INSERT INTO transactions(
                idempotency_key, account_id, posted_at, amount_cents,
                payee, memo, external_id, source, category_id, is_cleared, import_meta_json
            ) VALUES(?, ?, ?, ?, ?, ?, ?, 'ynab-csv', ?, ?, ?)
            ON CONFLICT(idempotency_key) DO UPDATE SET
                account_id = excluded.account_id,
                posted_at = excluded.posted_at,
                amount_cents = excluded.amount_cents,
                payee = excluded.payee,
                memo = excluded.memo,
                external_id = excluded.external_id,
                source = excluded.source,
                category_id = COALESCE(excluded.category_id, transactions.category_id),
                is_cleared = excluded.is_cleared,
                import_meta_json = excluded.import_meta_json
            """
        )

        # Read CSV with flexible header handling
        with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            # Normalize fieldnames to lowercase
            if reader.fieldnames:
                reader.fieldnames = [
                    (name or "").strip().lower() for name in reader.fieldnames
                ]

            for row in reader:
                # Normalize row keys to lowercase for access
                r = {k.strip().lower(): v for k, v in row.items()}

                date_iso = _parse_date(r.get("date") or r.get("posted") or r.get("transaction date") or "")
                posted_at = f"{date_iso}T00:00:00Z"

                payee = (r.get("payee") or r.get("description") or "").strip()
                memo = (r.get("memo") or r.get("notes") or "").strip()
                category_name = (r.get("category") or r.get("master category") or "").strip()

                amount_cents = _parse_amount(r)

                acct_name = (
                    account_override
                    if account_override
                    else (r.get("account") or r.get("account name") or "CSV Imports").strip()
                )
                local_account_id = _upsert_account(conn, name=acct_name, type_="unknown", currency="USD")

                # Category resolution via category_map(source='ynab-csv', external_id=category_name)
                category_id = None
                if category_name:
                    category_id = _lookup_category_map(
                        conn, source="ynab-csv", external_id=category_name
                    )
                if category_id is None:
                    category_id = holding_id

                is_cleared = _cleared_flag(r.get("cleared") or r.get("status"))

                idem_key = _build_idem(
                    "source:ynab-csv",
                    date_iso=date_iso,
                    account_name=acct_name,
                    amount_cents=amount_cents,
                    payee=payee,
                    memo=memo,
                    category=category_name,
                )

                import_meta = {
                    "csv_category": category_name,
                    "csv_account": acct_name,
                }

                conn.execute(
                    upsert_sql,
                    (
                        idem_key,
                        local_account_id,
                        posted_at,
                        amount_cents,
                        payee,
                        memo,
                        None,  # external_id not available for CSV
                        category_id,
                        is_cleared,
                        json.dumps(import_meta, ensure_ascii=False),
                    ),
                )
                rows_upserted += 1

        finished_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        conn.execute(
            "UPDATE ingest_audit SET run_finished_at = ?, rows_upserted = ?, status = ?, notes = ? WHERE id = ?",
            (finished_at, rows_upserted, "success", json.dumps(notes), audit_id),
        )

    return CsvImportResult(
        started_at=started_at,
        finished_at=finished_at,
        rows_upserted=rows_upserted,
        status=status,
        notes=json.dumps(notes),
    )

