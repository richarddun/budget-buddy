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
import tempfile
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


# ---- Routes ----


@router.get("/api/csv-import/upload-page", response_class=HTMLResponse)
async def csv_import_page(request: Request):
    """Render the CSV import page with drag-and-drop UI."""
    # Get available accounts for account mapping
    import sqlite3
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
    import sqlite3
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

    Accepts a JSON body with:
        account_name    — Account name to assign transactions to
        csv_content     — Raw CSV file content (base64 or direct)
        filename        — Original filename for audit trail

    Alternatively, accept multipart form data with the file.
    For simplicity, this route expects a re-upload in multipart form.
    """
    # Read the file from multipart form
    form = await request.form()
    file: Optional[UploadFile] = form.get("file")  # type: ignore
    account_name: str = form.get("account_name", "")

    if not file:
        raise HTTPException(status_code=400, detail="No file provided.")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file.")

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

        result = run_import(
            db_path=dbp,
            csv_path=Path(tmp.name),
            account_override=account_override,
        )

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
        }
    except Exception as e:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Import failed: {e}")
