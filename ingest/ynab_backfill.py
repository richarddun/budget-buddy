from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

from db.migrate import run_migrations
from ynab_sdk_client import YNABSdkClient


@dataclass
class BackfillResult:
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


def _upsert_account(
    conn: sqlite3.Connection,
    *,
    name: str,
    type_: str,
    currency: str,
) -> int:
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


def _map_category(
    conn: sqlite3.Connection, *, source: str, external_category_id: Optional[str]
) -> Optional[int]:
    if not external_category_id:
        return None
    cur = conn.execute(
        "SELECT internal_category_id FROM category_map WHERE source = ? AND external_id = ?",
        (source, external_category_id),
    )
    row = cur.fetchone()
    return int(row[0]) if row else None


def _ynab_accounts_map(client: YNABSdkClient, budget_id: str) -> Dict[str, Dict[str, Any]]:
    accounts = client.get_accounts(budget_id) or []
    out: Dict[str, Dict[str, Any]] = {}
    for a in accounts:
        ext_id = a.get("id")
        if not ext_id:
            continue
        out[ext_id] = a
    return out


def _to_cents(amount: Any) -> int:
    try:
        return int(round(float(amount) * 100))
    except Exception:
        return 0


def _cleared_flag(v: Any) -> int:
    s = (v or "").lower()
    return 1 if s in {"cleared", "reconciled", "true", "1"} else 0


def run_backfill(db_path: Path, *, months: int) -> BackfillResult:
    """Run idempotent backfill from YNAB for the last N months.

    - Reads YNAB creds from env (YNAB_TOKEN, YNAB_BUDGET_ID)
    - Upserts accounts encountered
    - Upserts transactions keyed by idempotency_key
    - Writes ingest_audit
    """

    ynab_token = os.getenv("YNAB_TOKEN")
    budget_id = os.getenv("YNAB_BUDGET_ID")
    if not ynab_token or not budget_id:
        raise RuntimeError("Missing YNAB_TOKEN or YNAB_BUDGET_ID in environment")

    # Ensure DB schema is present
    run_migrations(db_path)

    started_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    rows_upserted = 0
    status = "success"
    notes_obj: Dict[str, Any] = {}

    try:
        client = YNABSdkClient()
        since_date = (datetime.utcnow().date() - timedelta(days=30 * months)).isoformat()

        acct_map = _ynab_accounts_map(client, budget_id)
        txns = client.get_transactions(budget_id, since_date)

        with _connect(db_path) as conn:
            # Prepared statements
            upsert_sql = (
                """
                INSERT INTO transactions(
                    idempotency_key, account_id, posted_at, amount_cents,
                    payee, memo, external_id, source, category_id, is_cleared, import_meta_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?, 'ynab', ?, ?, ?)
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

            # Pre-insert audit row
            cur = conn.execute(
                "INSERT INTO ingest_audit(source, run_started_at, status, notes) VALUES(?, ?, ?, ?)",
                ("ynab", started_at, "running", json.dumps({"mode": "backfill", "months": months})),
            )
            audit_id = int(cur.lastrowid)

            for t in txns or []:
                ext_txn_id = t.get("id")
                ext_acct_id = t.get("account_id")
                acct_info = acct_map.get(ext_acct_id) or {}
                acct_name = acct_info.get("name") or f"YNAB {str(ext_acct_id)[:8]}"
                acct_type = acct_info.get("type") or "unknown"
                currency = (
                    acct_info.get("currency")
                    or acct_info.get("currency_code")
                    or "USD"
                )

                local_account_id = _upsert_account(
                    conn, name=acct_name, type_=acct_type, currency=currency
                )

                posted_date = t.get("date") or datetime.utcnow().date().isoformat()
                posted_at = f"{posted_date}T00:00:00Z"
                amount_cents = _to_cents(t.get("amount"))
                payee = t.get("payee_name")
                memo = t.get("memo")
                external_id = ext_txn_id
                source = "ynab"
                internal_cat_id = _map_category(
                    conn, source=source, external_category_id=t.get("category_id")
                )
                is_cleared = _cleared_flag(t.get("cleared"))

                idem_key = f"source:ynab:{ext_acct_id}:{ext_txn_id}"

                import_meta = {
                    "ynab_id": ext_txn_id,
                    "account_id": ext_acct_id,
                    "import_id": t.get("import_id"),
                    "flag_color": t.get("flag_color"),
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
                        external_id,
                        internal_cat_id,
                        is_cleared,
                        json.dumps(import_meta, ensure_ascii=False),
                    ),
                )
                rows_upserted += 1

            finished_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
            notes_obj.update(
                {
                    "mode": "backfill",
                    "months": months,
                    "since_date": since_date,
                    "transactions_seen": len(txns or []),
                }
            )
            conn.execute(
                "UPDATE ingest_audit SET run_finished_at = ?, rows_upserted = ?, status = ?, notes = ? WHERE id = ?",
                (finished_at, rows_upserted, "success", json.dumps(notes_obj), audit_id),
            )

    except Exception as e:
        status = "error"
        finished_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        notes_obj.update({"error": str(e)})
        # Best-effort audit write when failing
        try:
            with _connect(db_path) as conn:
                conn.execute(
                    "INSERT INTO ingest_audit(source, run_started_at, run_finished_at, rows_upserted, status, notes) VALUES(?, ?, ?, ?, ?, ?)",
                    (
                        "ynab",
                        started_at,
                        finished_at,
                        rows_upserted,
                        "error",
                        json.dumps(notes_obj),
                    ),
                )
        except Exception:
            pass

        return BackfillResult(
            started_at=started_at,
            finished_at=finished_at,
            rows_upserted=rows_upserted,
            status=status,
            notes=json.dumps(notes_obj),
        )

    return BackfillResult(
        started_at=started_at,
        finished_at=finished_at,
        rows_upserted=rows_upserted,
        status=status,
        notes=json.dumps(notes_obj),
    )

