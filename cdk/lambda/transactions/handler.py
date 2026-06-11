#!/usr/bin/env python3
"""
Budget Buddy — Transactions Lambda Handler

CRUD operations for transaction history.

API Gateway routes:
  GET  /transactions          → List transactions (paginated)
  GET  /transactions?since=YYYY-MM-DD  → Filter by date
  POST /transactions          → Create a transaction
  DELETE /transactions/{id}   → Delete by idempotency_key
"""

import json
import logging
import os
import sqlite3
import uuid
from datetime import date, datetime
from typing import Any, Optional

DB_PATH = os.environ.get('DB_PATH', '/mnt/efs/localdb/budget.db')
logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get('LOG_LEVEL', 'INFO'))


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _parse_body(event: dict) -> dict:
    body = event.get("body", "{}")
    if event.get("isBase64Encoded", False):
        import base64
        body = base64.b64decode(body).decode("utf-8")
    return json.loads(body) if body else {}


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in row.keys()}


def _error(status: int, message: str) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"error": message}),
    }


def _ok(data: Any) -> dict:
    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(data, default=str),
    }


def _handle_list(conn: sqlite3.Connection, event: dict) -> dict:
    """GET /transactions — list with optional date filter and pagination."""
    params = event.get("queryStringParameters") or {}
    since = params.get("since")
    page = int(params.get("page", "1"))
    page_size = min(int(params.get("page_size", "50")), 200)

    offset = (page - 1) * page_size

    if since:
        cur = conn.execute(
            """
            SELECT t.*, a.name AS account_name
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            WHERE a.is_active = 1
              AND DATE(t.posted_at) >= DATE(?)
            ORDER BY t.posted_at DESC
            LIMIT ? OFFSET ?
            """,
            (since, page_size, offset),
        )
        count_cur = conn.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            WHERE a.is_active = 1
              AND DATE(t.posted_at) >= DATE(?)
            """,
            (since,),
        )
    else:
        cur = conn.execute(
            """
            SELECT t.*, a.name AS account_name
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            WHERE a.is_active = 1
            ORDER BY t.posted_at DESC
            LIMIT ? OFFSET ?
            """,
            (page_size, offset),
        )
        count_cur = conn.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            WHERE a.is_active = 1
            """
        )

    transactions = [_row_to_dict(row) for row in cur.fetchall()]
    total = int(count_cur.fetchone()["cnt"])

    return _ok({
        "items": transactions,
        "count": len(transactions),
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    })


def _handle_create(conn: sqlite3.Connection, event: dict) -> dict:
    """POST /transactions — create a new transaction."""
    data = _parse_body(event)

    required = ["account_id", "amount_cents", "posted_at"]
    missing = [f for f in required if f not in data]
    if missing:
        return _error(400, f"Missing required fields: {', '.join(missing)}")

    idem_key = data.get("idempotency_key", f"api-{uuid.uuid4()}")

    # Check for duplicate
    existing = conn.execute(
        "SELECT idempotency_key FROM transactions WHERE idempotency_key = ?",
        (idem_key,),
    ).fetchone()
    if existing:
        return _error(409, f"Transaction with idempotency_key '{idem_key}' already exists")

    amount_cents = int(data["amount_cents"])
    # Convention: negative = outflow (spending), positive = inflow
    # If user passes positive for spending, negate it
    if amount_cents > 0 and data.get("type", "expense") == "expense":
        amount_cents = -abs(amount_cents)

    conn.execute(
        """
        INSERT OR IGNORE INTO transactions (
            idempotency_key, account_id, posted_at, amount_cents,
            payee, memo, source, category_id, is_cleared
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            idem_key,
            int(data["account_id"]),
            data["posted_at"],
            amount_cents,
            data.get("payee"),
            data.get("memo"),
            data.get("source", "api"),
            data.get("category_id"),
            int(data.get("is_cleared", 1)),
        ),
    )
    conn.commit()

    row = conn.execute(
        "SELECT * FROM transactions WHERE idempotency_key = ?",
        (idem_key,),
    ).fetchone()

    return {
        "statusCode": 201,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps({"transaction": _row_to_dict(row)}, default=str),
    }


def _handle_delete(conn: sqlite3.Connection, event: dict, tx_id: str) -> dict:
    """DELETE /transactions/{id} — delete by idempotency_key."""
    cur = conn.execute(
        "DELETE FROM transactions WHERE idempotency_key = ?",
        (tx_id,),
    )
    conn.commit()
    if cur.rowcount == 0:
        return _error(404, f"Transaction with idempotency_key '{tx_id}' not found")
    return _ok({"status": "deleted", "idempotency_key": tx_id})


def handler(event: dict, context: Any) -> dict[str, Any]:
    logger.info(f"Transactions handler: {event.get('routeKey', 'unknown')}")

    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path_params = event.get("pathParameters") or {}
    tx_id = path_params.get("id")

    conn = _connect()
    try:
        if method == "GET" and tx_id is None:
            return _handle_list(conn, event)
        elif method == "POST" and tx_id is None:
            return _handle_create(conn, event)
        elif method == "DELETE" and tx_id is not None:
            return _handle_delete(conn, event, tx_id)
        elif method == "GET" and tx_id is not None:
            row = conn.execute(
                "SELECT t.*, a.name AS account_name FROM transactions t JOIN accounts a ON a.id = t.account_id WHERE t.idempotency_key = ?",
                (tx_id,),
            ).fetchone()
            if not row:
                return _error(404, "Transaction not found")
            return _ok({"transaction": _row_to_dict(row)})
        else:
            return _error(405, f"Method {method} not allowed for this path")

    except sqlite3.OperationalError as e:
        logger.error(f"Database error: {e}")
        return _error(500, "Database error")
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        return _error(500, "Internal server error")
    finally:
        conn.close()


if __name__ == "__main__":
    # Simple test: list transactions
    event = {
        "routeKey": "GET /transactions",
        "rawPath": "/transactions",
        "requestContext": {"http": {"method": "GET", "path": "/transactions"}},
        "queryStringParameters": {"page": "1", "page_size": "5"},
        "pathParameters": {},
        "body": "{}",
    }
    result = handler(event, None)
    data = json.loads(result["body"])
    print(f"Found {data['count']} transactions (total: {data['total']})")
    for tx in data["items"][:3]:
        amt = int(tx["amount_cents"])
        print(f"  {tx['posted_at']} | {tx['payee'] or '—'} | €{abs(amt)/100:,.2f}")