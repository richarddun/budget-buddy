#!/usr/bin/env python3
"""
Budget Buddy — Commitments Lambda Handler

CRUD operations for recurring bill/commitment tracking.

API Gateway routes:
  GET    /commitments          → List all commitments
  GET    /commitments?type=X   → Filter by type
  POST   /commitments          → Create a commitment
  PUT    /commitments/{id}     → Update a commitment
  DELETE /commitments/{id}     → Delete a commitment
"""

import json
import logging
import os
import sqlite3
from datetime import date
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


# ── Helpers ──────────────────────────────────────────────────────

def _parse_body(event: dict) -> dict:
    """Parse JSON body from API Gateway event."""
    body = event.get("body", "{}")
    if event.get("isBase64Encoded", False):
        import base64
        body = base64.b64decode(body).decode("utf-8")
    return json.loads(body) if body else {}


def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a sqlite3.Row to a plain dict."""
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


def _created(data: Any) -> dict:
    return {
        "statusCode": 201,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(data, default=str),
    }


# ── Handlers ─────────────────────────────────────────────────────

def _handle_list(conn: sqlite3.Connection, event: dict) -> dict:
    """GET /commitments — list with optional type filter."""
    params = event.get("queryStringParameters") or {}
    commitment_type = params.get("type")

    if commitment_type:
        cur = conn.execute(
            "SELECT * FROM commitments WHERE LOWER(type) = LOWER(?) ORDER BY next_due_date ASC, name",
            (commitment_type.strip(),),
        )
    else:
        cur = conn.execute(
            "SELECT * FROM commitments ORDER BY next_due_date ASC, name"
        )

    commitments = [_row_to_dict(row) for row in cur.fetchall()]
    return _ok({"items": commitments, "count": len(commitments)})


def _handle_create(conn: sqlite3.Connection, event: dict) -> dict:
    """POST /commitments — create a new commitment."""
    data = _parse_body(event)

    required = ["name", "amount_cents", "next_due_date"]
    missing = [f for f in required if f not in data]
    if missing:
        return _error(400, f"Missing required fields: {', '.join(missing)}")

    cur = conn.execute(
        """
        INSERT INTO commitments (name, amount_cents, due_rule, next_due_date,
                                 priority, account_id, flexible_window_days,
                                 category_id, type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["name"].strip(),
            int(data["amount_cents"]),
            data.get("due_rule", "MONTHLY").strip().upper(),
            data["next_due_date"],
            int(data.get("priority", 1)),
            int(data.get("account_id", 1)),
            int(data.get("flexible_window_days", 0)),
            data.get("category_id"),
            data.get("type", "bill").strip().lower(),
        ),
    )
    conn.commit()

    new_id = cur.lastrowid
    row = conn.execute("SELECT * FROM commitments WHERE id = ?", (new_id,)).fetchone()
    return _created({"commitment": _row_to_dict(row)})


def _handle_update(conn: sqlite3.Connection, event: dict, commitment_id: int) -> dict:
    """PUT /commitments/{id} — update a commitment."""
    data = _parse_body(event)

    # Build SET clause dynamically from provided fields
    field_map = {
        "name": "name",
        "amount_cents": "amount_cents",
        "due_rule": "due_rule",
        "next_due_date": "next_due_date",
        "priority": "priority",
        "account_id": "account_id",
        "flexible_window_days": "flexible_window_days",
        "category_id": "category_id",
        "type": "type",
    }

    sets = []
    params = []
    for json_key, db_col in field_map.items():
        if json_key in data:
            sets.append(f"{db_col} = ?")
            params.append(data[json_key])

    if not sets:
        return _error(400, "No fields provided to update")

    params.append(commitment_id)
    conn.execute(
        f"UPDATE commitments SET {', '.join(sets)} WHERE id = ?",
        params,
    )
    conn.commit()

    row = conn.execute("SELECT * FROM commitments WHERE id = ?", (commitment_id,)).fetchone()
    if not row:
        return _error(404, "Commitment not found")
    return _ok({"commitment": _row_to_dict(row)})


def _handle_delete(conn: sqlite3.Connection, commitment_id: int) -> dict:
    """DELETE /commitments/{id} — delete a commitment."""
    cur = conn.execute("DELETE FROM commitments WHERE id = ?", (commitment_id,))
    conn.commit()
    if cur.rowcount == 0:
        return _error(404, "Commitment not found")
    return _ok({"status": "deleted", "id": commitment_id})


# ── Main handler ─────────────────────────────────────────────────

def handler(event: dict, context: Any) -> dict[str, Any]:
    """
    Route incoming API Gateway HTTP v2 requests to the right handler.
    """
    logger.info(f"Commitments handler: {event.get('routeKey', 'unknown')}")

    # Parse route and method
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath", "")
    path_params = event.get("pathParameters") or {}

    conn = _connect()
    try:
        # Extract {id} from path if present
        commitment_id = path_params.get("id")
        if commitment_id:
            commitment_id = int(commitment_id)

        # Route
        if method == "GET" and commitment_id is None:
            return _handle_list(conn, event)
        elif method == "POST" and commitment_id is None:
            return _handle_create(conn, event)
        elif method == "PUT" and commitment_id is not None:
            return _handle_update(conn, event, commitment_id)
        elif method == "DELETE" and commitment_id is not None:
            return _handle_delete(conn, commitment_id)
        elif method == "GET" and commitment_id is not None:
            row = conn.execute(
                "SELECT * FROM commitments WHERE id = ?", (commitment_id,)
            ).fetchone()
            if not row:
                return _error(404, "Commitment not found")
            return _ok({"commitment": _row_to_dict(row)})
        else:
            return _error(405, f"Method {method} not allowed for this path")

    except ValueError as e:
        return _error(400, f"Invalid input: {e}")
    except sqlite3.OperationalError as e:
        logger.error(f"Database error: {e}")
        return _error(500, "Database error")
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        return _error(500, "Internal server error")
    finally:
        conn.close()


# ── Local testing ────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "list":
        event = {
            "routeKey": "GET /commitments",
            "rawPath": "/commitments",
            "requestContext": {"http": {"method": "GET", "path": "/commitments"}},
            "queryStringParameters": {},
            "pathParameters": {},
            "body": "{}",
        }
    elif len(sys.argv) > 1 and sys.argv[1] == "create":
        event = {
            "routeKey": "POST /commitments",
            "rawPath": "/commitments",
            "requestContext": {"http": {"method": "POST", "path": "/commitments"}},
            "queryStringParameters": {},
            "pathParameters": {},
            "body": json.dumps({
                "name": "Test Netflix",
                "amount_cents": 1499,
                "next_due_date": "2026-07-01",
                "due_rule": "MONTHLY",
                "type": "bill",
            }),
        }
    else:
        event = {
            "routeKey": "GET /commitments",
            "rawPath": "/commitments",
            "requestContext": {"http": {"method": "GET", "path": "/commitments"}},
            "pathParameters": {},
            "body": "{}",
        }

    result = handler(event, None)
    print(json.dumps(json.loads(result["body"]), indent=2))