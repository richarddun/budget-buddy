#!/usr/bin/env python3
"""
Budget Buddy — Overview Lambda Handler

Computes the overview digest: current balance, safe-to-spend today,
next cliff date, and top commitments over the next 14 days.

Uses only Python stdlib — sqlite3 built-in, no third-party deps.

Expected API Gateway HTTP v2 event:
  GET /overview
  GET /digest
"""

import json
import logging
import os
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any, Optional

# ── Configuration ────────────────────────────────────────────────
DB_PATH = os.environ.get('DB_PATH', '/mnt/efs/localdb/budget.db')
logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get('LOG_LEVEL', 'INFO'))


# ── Database helpers ─────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    """Open SQLite database with row factory and WAL mode."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


# ── Business logic (ported from forecast/calendar.py + api/overview.py) ─

def _format_money(cents: Optional[int]) -> str:
    if cents is None:
        return "—"
    return f"€{cents/100:,.2f}"


def _load_latest_snapshot(conn: sqlite3.Connection) -> Optional[dict]:
    """Load the most recent forecast snapshot."""
    cur = conn.execute(
        """
        SELECT created_at, horizon_start, horizon_end, json_payload,
               min_balance_cents, min_balance_date
        FROM forecast_snapshot
        ORDER BY created_at DESC
        LIMIT 1
        """
    )
    row = cur.fetchone()
    if not row:
        return None
    return {
        "created_at": row["created_at"],
        "horizon_start": row["horizon_start"],
        "horizon_end": row["horizon_end"],
        "json_payload": row["json_payload"],
        "min_balance_cents": row["min_balance_cents"],
        "min_balance_date": row["min_balance_date"],
    }


def _compute_current_balance(conn: sqlite3.Connection) -> int:
    """Sum of all active account cleared balances from transactions."""
    cur = conn.execute(
        """
        SELECT COALESCE(SUM(t.amount_cents), 0) AS balance
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        WHERE a.is_active = 1 AND t.is_cleared = 1
        """
    )
    return int(cur.fetchone()["balance"])


def _compute_safe_to_spend(
    conn: sqlite3.Connection,
    current_balance_cents: int,
    horizon_days: int = 30,
) -> int:
    """
    Safe-to-spend = current balance - sum of all upcoming commitments
    within the horizon. This gives you the 'buffer' before you hit red.
    """
    today = date.today()
    end = today + timedelta(days=horizon_days)

    cur = conn.execute(
        """
        SELECT COALESCE(SUM(c.amount_cents), 0) AS total
        FROM commitments c
        WHERE c.next_due_date IS NOT NULL
          AND DATE(c.next_due_date) >= DATE(?)
          AND DATE(c.next_due_date) <= DATE(?)
        """,
        (today.isoformat(), end.isoformat()),
    )
    upcoming = int(cur.fetchone()["total"])

    # Also check key spend events in the same window
    cur = conn.execute(
        """
        SELECT COALESCE(SUM(k.planned_amount_cents), 0) AS total
        FROM key_spend_events k
        WHERE k.event_date IS NOT NULL
          AND DATE(k.event_date) >= DATE(?)
          AND DATE(k.event_date) <= DATE(?)
        """,
        (today.isoformat(), end.isoformat()),
    )
    upcoming += int(cur.fetchone()["total"])

    # Safe-to-spend = current balance - upcoming obligations
    return current_balance_cents - upcoming


def _get_top_commitments(
    conn: sqlite3.Connection,
    limit: int = 5,
    horizon_days: int = 14,
) -> list[dict[str, Any]]:
    """Top upcoming commitments sorted by date."""
    today = date.today()
    end = today + timedelta(days=horizon_days)

    cur = conn.execute(
        """
        SELECT c.name, c.amount_cents, c.next_due_date, c.type
        FROM commitments c
        WHERE c.next_due_date IS NOT NULL
          AND DATE(c.next_due_date) >= DATE(?)
          AND DATE(c.next_due_date) <= DATE(?)
        ORDER BY DATE(c.next_due_date) ASC, c.amount_cents DESC
        LIMIT ?
        """,
        (today.isoformat(), end.isoformat(), limit),
    )

    return [
        {
            "name": row["name"],
            "amount_cents": int(row["amount_cents"]),
            "amount_display": _format_money(int(row["amount_cents"])),
            "due_date": row["next_due_date"],
            "type": row["type"],
        }
        for row in cur.fetchall()
    ]


def _compute_digest() -> dict[str, Any]:
    """Assemble the full overview digest from the database."""

    conn = _connect()
    try:
        # 1. Current balance
        current_balance_cents = _compute_current_balance(conn)
        current_balance = _format_money(current_balance_cents)

        # 2. Safe-to-spend today (30-day horizon)
        safe_to_spend_cents = _compute_safe_to_spend(conn, current_balance_cents, 30)
        safe_to_spend = _format_money(safe_to_spend_cents)

        # 3. Latest snapshot for min balance info
        snapshot = _load_latest_snapshot(conn)
        min_balance_cents = None
        min_balance_date = None
        if snapshot:
            min_balance_cents = snapshot.get("min_balance_cents")
            min_balance_date = snapshot.get("min_balance_date")

        # 4. Next commitments
        top_commitments = _get_top_commitments(conn, limit=5, horizon_days=14)

        # 5. Account summary
        cur = conn.execute(
            """
            SELECT a.name, a.type,
                   COALESCE(SUM(t.amount_cents), 0) AS balance
            FROM accounts a
            LEFT JOIN transactions t ON t.account_id = a.id AND t.is_cleared = 1
            WHERE a.is_active = 1
            GROUP BY a.id, a.name, a.type
            ORDER BY a.name
            """
        )
        accounts = [
            {
                "name": row["name"],
                "type": row["type"],
                "balance_cents": int(row["balance"]),
                "balance_display": _format_money(int(row["balance"])),
            }
            for row in cur.fetchall()
        ]

        return {
            "current_balance_cents": current_balance_cents,
            "current_balance_display": current_balance,
            "safe_to_spend_cents": safe_to_spend_cents,
            "safe_to_spend_display": safe_to_spend,
            "min_balance_cents": min_balance_cents,
            "min_balance_date": min_balance_date,
            "top_commitments_next_14_days": top_commitments,
            "accounts": accounts,
            "generated_at": datetime.utcnow().isoformat() + "Z",
        }

    finally:
        conn.close()


# ── Lambda handler ───────────────────────────────────────────────

def handler(event: dict, context: Any) -> dict[str, Any]:
    """
    Lambda handler for API Gateway HTTP v2 proxy integration.

    Returns JSON overview digest. In the future, could return
    HTML fragments for HTMX if Content-Type header requests it.
    """
    logger.info("Overview handler invoked")

    try:
        digest = _compute_digest()

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps(digest, indent=2, default=str),
        }

    except sqlite3.OperationalError as e:
        logger.error(f"Database error: {e}")
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "error": "Database error",
                "detail": str(e),
            }),
        }
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "error": "Internal server error",
            }),
        }


# ── Local testing (standalone) ───────────────────────────────────
if __name__ == "__main__":
    # Simulate an API Gateway event
    test_event = {
        "version": "2.0",
        "routeKey": "GET /overview",
        "rawPath": "/overview",
        "headers": {"Content-Type": "application/json"},
        "requestContext": {
            "http": {"method": "GET", "path": "/overview"},
        },
    }
    result = handler(test_event, None)
    print(json.dumps(json.loads(result["body"]), indent=2))