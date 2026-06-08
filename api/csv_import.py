"""
CSV Import API — Upload, preview, and import bank statement CSVs.

Endpoints:
    GET  /api/csv-import/upload-page  — Render the CSV import HTML page
    POST /api/csv-import/preview      — Upload CSV, detect parser, return preview rows
    POST /api/csv-import/confirm      — Confirm import with account mapping & options
"""

from __future__ import annotations

import csv
import io
import json
import os
import shutil
import sqlite3
import tempfile
from datetime import date as _date
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ingest.csv_importer import run_import
from ingest.parsers import detect_parser, parse_known_rows, registered_parsers

router = APIRouter()

# ---- Template setup ----
_templates = Jinja2Templates(directory="templates")

# ---- Constants ----
UPLOAD_DIR = Path("uploads/csv_import")
MAX_PREVIEW_ROWS = 20


def _get_upload_dir() -> Path:
    """Return the upload directory, creating it if needed."""
    d = UPLOAD_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _db_path() -> Path:
    """Resolve the default SQLite database path."""
    from forecast.calendar import _default_db_path
    return _default_db_path()


def _read_csv_preview(content: bytes) -> tuple[List[str], List[Dict[str, str]]]:
    """Read CSV content, returning (headers, rows) for preview.

    Handles BOM (utf-8-sig), strips whitespace from headers and values.
    """
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    # Normalise headers
    headers = [(h or "").strip() for h in (reader.fieldnames or [])]
    rows: List[Dict[str, str]] = []
    for i, row in enumerate(reader):
        if i >= MAX_PREVIEW_ROWS:
            break
        # Normalise row keys to lowercase for parser compatibility
        normalised = {k.strip().lower(): v.strip() for k, v in row.items()}
        rows.append(normalised)
    return headers, rows


def _resolve_account_id(conn: sqlite3.Connection, account_name: str) -> Optional[int]:
    """Look up an account by name. Returns id or None."""
    cur = conn.execute(
        "SELECT id FROM accounts WHERE name = ? AND is_active = 1",
        (account_name.strip(),),
    )
    row = cur.fetchone()
    return int(row[0]) if row else None


def _upsert_normalize_anchor(conn: sqlite3.Connection, *, account_id: int, balance_cents: int, as_of_date: str) -> dict:
    """Upsert an anchor for the given account.

    Preserves the existing min_floor_cents if present.
    """
    cur = conn.execute(
        "SELECT min_floor_cents FROM account_anchors WHERE account_id = ?",
        (account_id,),
    )
    existing = cur.fetchone()
    mfc_val = int(existing[0]) if existing and existing[0] is not None else None

    conn.execute(
        """
        INSERT INTO account_anchors(account_id, anchor_date, anchor_balance_cents, min_floor_cents)
        VALUES(?, ?, ?, ?)
        ON CONFLICT(account_id) DO UPDATE SET
            anchor_date = excluded.anchor_date,
            anchor_balance_cents = excluded.anchor_balance_cents,
            min_floor_cents = COALESCE(excluded.min_floor_cents, account_anchors.min_floor_cents)
        """,
        (account_id, as_of_date, balance_cents, mfc_val),
    )
    conn.commit()

    return {
        "account_id": account_id,
        "anchor_date": as_of_date,
        "anchor_balance_cents": balance_cents,
        "min_floor_cents": mfc_val,
    }


# ---- Routes ----


@router.get("/api/csv-import/upload-page", response_class=HTMLResponse)
async def csv_import_page(request: Request):
    """Render the CSV import page with drag-and-drop UI."""
    # Get available accounts for account mapping
    dbp = _db_path()
    accounts: List[Dict[str, Any]] = []
    try:
        with sqlite3.connect(dbp) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, name, type, currency FROM accounts WHERE is_active = 1 ORDER BY name"
            ).fetchall()
            accounts = [
                {"id": int(r["id"]), "name": r["name"], "type": r["type"], "currency": r["currency"]}
                for r in rows
            ]
    except Exception:
        pass  # No DB yet — template handles empty accounts gracefully

    # Available parsers
    parsers_info = [
        {"label": p.BANK_LABEL} for p in registered_parsers()
    ]

    return _templates.TemplateResponse(
        request,
        "csv_import.html",
        {
            "request": request,
            "accounts": accounts,
            "parsers": parsers_info,
        },
    )


@router.post("/api/csv-import/preview")
async def csv_import_preview(file: UploadFile = File(...)):
    """Upload a CSV file, detect its format, and return a preview.

    Returns JSON with:
        filename        — Original uploaded filename
        detected_parser — Bank label (or null if unknown)
        headers         — Parsed header columns
        rows            — Up to MAX_PREVIEW_ROWS of parsed rows
        total_rows      — Total number of rows in CSV
        can_import      — Whether auto-detection succeeded
        accounts        — Available accounts for mapping
    """
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted.")

    content = await file.read()
    if not content.strip():
        raise HTTPException(status_code=400, detail="Empty file uploaded.")

    try:
        headers, preview_rows = _read_csv_preview(content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse CSV: {e}")

    # Detect parser
    parser = detect_parser(headers)
    parser_label = parser.BANK_LABEL if parser else None

    # If parser detected, run its parse_row across preview rows
    parsed_rows: List[Dict[str, Any]] = []
    if parser:
        parsed_rows = parse_known_rows(parser, preview_rows)

    # Get accounts for mapping
    dbp = _db_path()
    accounts: List[Dict[str, Any]] = []
    try:
        with sqlite3.connect(dbp) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, name, type, currency FROM accounts WHERE is_active = 1 ORDER BY name"
            ).fetchall()
            accounts = [
                {"id": int(r["id"]), "name": r["name"], "type": r["type"], "currency": r["currency"]}
                for r in rows
            ]
    except Exception:
        pass

    return {
        "filename": file.filename,
        "detected_parser": parser_label,
        "headers": headers,
        "rows": parsed_rows[:MAX_PREVIEW_ROWS],
        "total_rows": len(preview_rows) if not parser else len(parsed_rows),
        "can_import": parser is not None,
        "accounts": accounts,
    }


@router.post("/api/csv-import/confirm")
async def csv_import_confirm(
    request: Request,
):
    """Confirm and execute the CSV import.

    Accepts multipart form data with:
        file                    — The CSV file (required)
        account_name            — Account name to assign transactions to (optional)
        normalize_balance       — "1" or "true" to enable normalize (optional)
        normalize_balance_cents — Current actual balance in cents (required if normalize)
        normalize_as_of         — Date the balance is as of (YYYY-MM-DD, default: today)

    Returns import result with optional normalize info.
    """
    # Read the file from multipart form
    form = await request.form()
    file: Optional[UploadFile] = form.get("file")  # type: ignore
    account_name: str = form.get("account_name", "")
    normalize_balance: str = form.get("normalize_balance", "")
    normalize_balance_cents: str = form.get("normalize_balance_cents", "")
    normalize_as_of: str = form.get("normalize_as_of", "")

    if not file:
        raise HTTPException(status_code=400, detail="No file provided.")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file.")

    should_normalize = normalize_balance.strip().lower() in ("1", "true", "yes", "on")

    # Validate normalize fields if enabled
    if should_normalize:
        if not normalize_balance_cents.strip():
            raise HTTPException(status_code=400, detail="normalize_balance_cents is required when normalize is enabled.")
        try:
            norm_cents = int(normalize_balance_cents.strip())
        except ValueError:
            raise HTTPException(status_code=400, detail="normalize_balance_cents must be an integer (cents).")

        if normalize_as_of.strip():
            try:
                _date.fromisoformat(normalize_as_of.strip())
            except ValueError:
                raise HTTPException(status_code=400, detail="normalize_as_of must be YYYY-MM-DD.")
            norm_date = normalize_as_of.strip()
        else:
            norm_date = _date.today().isoformat()
    else:
        norm_cents = None
        norm_date = None

    # Save to temp file
    tmp = tempfile.NamedTemporaryFile(
        mode="wb",
        suffix=".csv",
        prefix="budget_import_",
        delete=False,
    )
    try:
        tmp.write(content)
        tmp.close()

        dbp = _db_path()
        account_override = account_name.strip() or None

        # ---- Parse through the bank parser system ----
        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        raw_rows: List[Dict[str, str]] = list(reader)
        headers = [(h or "").strip() for h in (reader.fieldnames or [])]

        from ingest.parsers import detect_parser
        parser = detect_parser(headers)

        if not parser:
            raise HTTPException(
                status_code=400,
                detail=f"Unrecognised CSV format. Headers: {headers[:6]}"
            )

        # Parse every row through the detected parser
        parsed_rows = []
        for raw_row in raw_rows:
            try:
                pr = parser.parse_row(raw_row)
                if isinstance(pr, dict) and pr.get("date"):
                    parsed_rows.append(pr)
            except Exception:
                continue

        if not parsed_rows:
            raise HTTPException(status_code=400, detail="No parseable rows found in CSV.")

        from ingest.csv_importer import run_import_from_parsed_rows
        result = run_import_from_parsed_rows(
            db_path=dbp,
            parsed_rows=parsed_rows,
            account_override=account_override,
        )

        # ---- Normalize (upsert anchor) if requested ----
        normalize_result = None
        if should_normalize and norm_cents is not None:
            # Determine which account to anchor
            resolve_acct = account_override.strip() if account_override.strip() else None
            if not resolve_acct:
                # If no account override, try to infer from CSV data
                # Fall back to the first active account
                with sqlite3.connect(dbp) as conn:
                    row = conn.execute(
                        "SELECT id, name FROM accounts WHERE is_active = 1 ORDER BY id LIMIT 1"
                    ).fetchone()
                    if row:
                        resolve_acct = row["name"] if isinstance(row, sqlite3.Row) else str(row[1])

            if resolve_acct:
                with sqlite3.connect(dbp) as conn:
                    conn.row_factory = sqlite3.Row
                    aid = _resolve_account_id(conn, resolve_acct)
                    if aid is not None:
                        anchor = _upsert_normalize_anchor(
                            conn,
                            account_id=aid,
                            balance_cents=norm_cents,
                            as_of_date=norm_date,
                        )
                        normalize_result = {
                            "account_id": anchor["account_id"],
                            "anchor_date": anchor["anchor_date"],
                            "anchor_balance_cents": anchor["anchor_balance_cents"],
                        }
                    else:
                        normalize_result = {"error": f"Account '{resolve_acct}' not found in database."}

        # Clean up temp file
        try:
            os.unlink(tmp.name)
        except Exception:
            pass

        return {
            "status": result.status,
            "rows_upserted": result.rows_upserted,
            "started_at": result.started_at,
            "finished_at": result.finished_at,
            "normalize": normalize_result,
        }
    except Exception as e:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Import failed: {e}")
