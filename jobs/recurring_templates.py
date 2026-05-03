"""Recurring transaction templates — auto-create transactions from templates.

This module provides:
- Template CRUD via the API layer
- `run_recurring_auto_create()` — invoked by daily ingestion to auto-create
  transactions for templates whose next_due_date has arrived (or is within
  a lookahead window).
- Deduplication via `recurring_instances` table.

Design:
- Each `recurring_templates` row has a `next_due_date`, `due_rule`, and
  `auto_create` flag.
- `run_recurring_auto_create()` finds templates where `next_due_date` is
  today or earlier, creates a transaction (if not already generated), and
  advances `next_due_date` by the `due_rule`.
- Templates linked to `commitments` or `scheduled_inflows` can optionally
  sync their `next_due_date` from the source table.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional
import uuid

from db.migrate import run_migrations

logger = logging.getLogger("uvicorn.error")

DEFAULT_DB_PATH = Path("localdb/budget.db")
DEFAULT_LOOKAHEAD_DAYS = 1  # How many days ahead to look for due templates


# ─── Helpers ────────────────────────────────────────────────────────────────

def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _advance_due_date(current: date, rule: str) -> date:
    """Advance a due date by one period according to the rule."""
    rule_norm = (rule or "MONTHLY").strip().upper()
    if rule_norm == "WEEKLY":
        return current + timedelta(days=7)
    elif rule_norm == "BIWEEKLY":
        return current + timedelta(days=14)
    elif rule_norm in ("MONTHLY", "MONTHLY_BY_DATE"):
        # Advance by one month, clamping to end of month if needed
        year = current.year + (current.month // 12)
        month = (current.month % 12) + 1
        if month == 1:
            year += 1
        # Clamp day to days in target month
        import calendar as _cal
        max_day = _cal.monthrange(year, month)[1]
        day = min(current.day, max_day)
        return date(year, month, day)
    elif rule_norm in ("ANNUAL", "YEARLY"):
        return date(current.year + 1, current.month, current.day)
    else:
        # ONE_OFF or unknown — don't advance (won't recur)
        return current


def _ensure_migrations(db_path: Path) -> None:
    """Run migrations so the recurring_templates tables exist."""
    run_migrations(db_path)


# ─── Core: Auto-create logic ────────────────────────────────────────────────

def run_recurring_auto_create(
    db_path: Path = DEFAULT_DB_PATH,
    lookahead_days: int = DEFAULT_LOOKAHEAD_DAYS,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Find due recurring templates and auto-create transactions.

    Scans templates where:
    - is_active = 1
    - auto_create = 1
    - next_due_date is not NULL
    - next_due_date <= today + lookahead_days

    For each, if no `recurring_instances` row exists for that template+due_date,
    creates a transaction and records the instance.

    Returns a summary dict with counts and details.
    """
    _ensure_migrations(db_path)

    today = date.today()
    cutoff = today + timedelta(days=lookahead_days)
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    created_count = 0
    skipped_count = 0

    conn = _connect(db_path)
    try:
        # Find due templates
        rows = conn.execute(
            """
            SELECT id, name, amount_cents, due_rule, next_due_date,
                   account_id, category_id, payee, memo, type,
                   source_commitment_id, source_inflow_id, auto_create
            FROM recurring_templates
            WHERE is_active = 1
              AND auto_create = 1
              AND next_due_date IS NOT NULL
              AND DATE(next_due_date) <= ?
            ORDER BY next_due_date ASC, id ASC
            """,
            (cutoff.isoformat(),),
        ).fetchall()

        for row in rows:
            tid = int(row["id"])
            due_str = row["next_due_date"]
            if not due_str:
                continue

            due_date = date.fromisoformat(due_str)

            # Check if already processed
            existing = conn.execute(
                "SELECT 1 FROM recurring_instances WHERE template_id = ? AND due_date = ?",
                (tid, due_str),
            ).fetchone()

            if existing:
                skipped_count += 1
                results.append({
                    "template_id": tid,
                    "name": row["name"],
                    "due_date": due_str,
                    "action": "already_processed",
                })
                continue

            # Build the transaction
            amount_cents = int(row["amount_cents"])
            ttype = (row["type"] or "expense").strip().lower()
            # In our transaction system: positive = outflow, negative = inflow
            if ttype in ("income", "inflow") and amount_cents > 0:
                tx_amount = -amount_cents  # Inflows are negative
            elif ttype in ("expense", "outflow") and amount_cents > 0:
                tx_amount = abs(amount_cents)  # Expenses are positive
            else:
                tx_amount = amount_cents

            payee = row["payee"] or row["name"]
            memo = row["memo"] or f"Auto-created from recurring template #{tid}"
            account_id = int(row["account_id"])
            category_id = int(row["category_id"]) if row["category_id"] is not None else None

            if dry_run:
                results.append({
                    "template_id": tid,
                    "name": row["name"],
                    "due_date": due_str,
                    "action": "dry_run_would_create",
                    "amount_cents": tx_amount,
                    "payee": payee,
                })
                created_count += 1
                continue

            try:
                # Generate idempotency key
                idem_key = f"recurring:{tid}:{due_str}:{uuid.uuid4().hex[:8]}"

                # Insert the transaction
                posted_at = f"{due_str}T00:00:00Z"
                conn.execute(
                    """
                    INSERT OR IGNORE INTO transactions(
                        idempotency_key, account_id, posted_at, amount_cents,
                        payee, memo, category_id, source, is_cleared
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        idem_key,
                        account_id,
                        posted_at,
                        tx_amount,
                        payee,
                        memo,
                        category_id,
                        "recurring",
                        0,  # not cleared initially
                    ),
                )

                # Record the instance
                conn.execute(
                    """
                    INSERT INTO recurring_instances(
                        template_id, due_date, idempotency_key, status
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (tid, due_str, idem_key, "created"),
                )

                # Advance the next_due_date
                new_due = _advance_due_date(due_date, row["due_rule"])
                conn.execute(
                    "UPDATE recurring_templates SET next_due_date = ?, last_created_date = ?, updated_at = datetime('now') WHERE id = ?",
                    (new_due.isoformat(), due_str, tid),
                )

                conn.commit()
                created_count += 1
                results.append({
                    "template_id": tid,
                    "name": row["name"],
                    "due_date": due_str,
                    "action": "created",
                    "idempotency_key": idem_key,
                    "next_due_date": new_due.isoformat(),
                })

            except Exception as exc:
                conn.rollback()
                logger.exception(f"Failed to auto-create for template #{tid}: {exc}")
                errors.append({
                    "template_id": tid,
                    "name": row["name"],
                    "due_date": due_str,
                    "error": str(exc),
                })

    finally:
        conn.close()

    return {
        "status": "ok" if not errors else "partial",
        "run_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "dry_run": dry_run,
        "templates_found": len(rows) if 'rows' in dir() else 0,
        "created": created_count,
        "skipped": skipped_count,
        "errors": len(errors),
        "results": results,
        "error_details": errors,
    }


# ─── Template management helpers ────────────────────────────────────────────

def list_templates(db_path: Path = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    """List all recurring templates with computed fields."""
    _ensure_migrations(db_path)
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT t.id, t.name, t.amount_cents, t.due_rule, t.next_due_date,
                   t.account_id, a.name AS account_name,
                   t.category_id, t.payee, t.memo, t.type,
                   t.source_commitment_id, t.source_inflow_id,
                   t.auto_create, t.last_created_date, t.is_active,
                   t.created_at, t.updated_at
            FROM recurring_templates t
            LEFT JOIN accounts a ON a.id = t.account_id
            ORDER BY t.next_due_date ASC NULLS LAST, t.name ASC
            """
        ).fetchall()

        return [
            {
                "id": int(r["id"]),
                "name": r["name"],
                "amount_cents": int(r["amount_cents"]),
                "due_rule": r["due_rule"],
                "next_due_date": r["next_due_date"],
                "account_id": int(r["account_id"]) if r["account_id"] is not None else None,
                "account_name": r["account_name"],
                "category_id": int(r["category_id"]) if r["category_id"] is not None else None,
                "payee": r["payee"],
                "memo": r["memo"],
                "type": r["type"],
                "source_commitment_id": int(r["source_commitment_id"]) if r["source_commitment_id"] is not None else None,
                "source_inflow_id": int(r["source_inflow_id"]) if r["source_inflow_id"] is not None else None,
                "auto_create": bool(r["auto_create"]),
                "last_created_date": r["last_created_date"],
                "is_active": bool(r["is_active"]),
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]
    finally:
        conn.close()


def generate_templates_from_commitments(
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """Scan commitments and scheduled_inflows for templates that don't exist yet.

    Auto-creates a recurring_templates row for each commitment/inflow that
    doesn't already have a linked template.
    """
    _ensure_migrations(db_path)
    conn = _connect(db_path)
    try:
        created = 0
        skipped = 0
        details: list[dict[str, Any]] = []

        # From commitments
        commitments = conn.execute(
            """
            SELECT c.id, c.name, c.amount_cents, c.due_rule, c.next_due_date,
                   c.account_id, c.category_id, c.type
            FROM commitments c
            WHERE c.next_due_date IS NOT NULL
              AND c.id NOT IN (
                  SELECT source_commitment_id FROM recurring_templates
                  WHERE source_commitment_id IS NOT NULL
              )
            """
        ).fetchall()

        for c in commitments:
            cid = int(c["id"])
            # Check if a template with same name exists (prevent duplicates)
            existing = conn.execute(
                "SELECT 1 FROM recurring_templates WHERE name = ? AND is_active = 1",
                (c["name"],),
            ).fetchone()
            if existing:
                skipped += 1
                details.append({
                    "source": f"commitment:{cid}",
                    "name": c["name"],
                    "action": "skipped_name_exists",
                })
                continue

            conn.execute(
                """
                INSERT INTO recurring_templates(
                    name, amount_cents, due_rule, next_due_date,
                    account_id, category_id, type,
                    source_commitment_id, auto_create,
                    payee, memo
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    c["name"],
                    int(c["amount_cents"]),
                    c["due_rule"],
                    c["next_due_date"],
                    int(c["account_id"]),
                    int(c["category_id"]) if c["category_id"] is not None else None,
                    c["type"] or "expense",
                    cid,
                    c["name"],  # payee
                    f"Auto-created from commitment: {c['name']}",
                ),
            )
            created += 1
            details.append({
                "source": f"commitment:{cid}",
                "name": c["name"],
                "action": "created",
            })

        # From scheduled_inflows
        inflows = conn.execute(
            """
            SELECT s.id, s.name, s.amount_cents, s.due_rule, s.next_due_date,
                   s.account_id, s.type
            FROM scheduled_inflows s
            WHERE s.next_due_date IS NOT NULL
              AND s.id NOT IN (
                  SELECT source_inflow_id FROM recurring_templates
                  WHERE source_inflow_id IS NOT NULL
              )
            """
        ).fetchall()

        for s in inflows:
            sid = int(s["id"])
            existing = conn.execute(
                "SELECT 1 FROM recurring_templates WHERE name = ? AND is_active = 1",
                (s["name"],),
            ).fetchone()
            if existing:
                skipped += 1
                details.append({
                    "source": f"inflow:{sid}",
                    "name": s["name"],
                    "action": "skipped_name_exists",
                })
                continue

            conn.execute(
                """
                INSERT INTO recurring_templates(
                    name, amount_cents, due_rule, next_due_date,
                    account_id, category_id, type,
                    source_inflow_id, auto_create,
                    payee, memo
                ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, 1, ?, ?)
                """,
                (
                    s["name"],
                    int(s["amount_cents"]),
                    s["due_rule"],
                    s["next_due_date"],
                    int(s["account_id"]),
                    "income",
                    sid,
                    s["name"],
                    f"Auto-created from scheduled inflow: {s['name']}",
                ),
            )
            created += 1
            details.append({
                "source": f"inflow:{sid}",
                "name": s["name"],
                "action": "created",
            })

        conn.commit()
    finally:
        conn.close()

    return {
        "status": "ok",
        "created": created,
        "skipped": skipped,
        "details": details,
    }
