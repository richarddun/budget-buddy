from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

from q.packs import assemble_pack


router = APIRouter()


EXPORT_DIR = Path(os.getenv("EXPORT_DIR") or "localdb/exports")


def _stable_serialize(obj: Any) -> str:
    """Stable JSON serialization for hashing (sorted keys, compact)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def redact_pack(pack: Dict[str, Any], *, include_pii: bool = False, include_memos: bool = False) -> Dict[str, Any]:
    """Return a shallowly-redacted copy of the pack for export stability.

    Redacts known PII fields (payee, memo) unless toggled on.
    """
    def _redact_inplace(d: Any) -> Any:
        if isinstance(d, dict):
            out = {}
            for k, v in d.items():
                if not include_pii and k in ("payee", "payee_name"):
                    out[k] = "REDACTED"
                elif not include_memos and k == "memo":
                    out[k] = None
                else:
                    out[k] = _redact_inplace(v)
            return out
        if isinstance(d, list):
            return [_redact_inplace(x) for x in d]
        return d

    return _redact_inplace(pack)


def compute_export_hash(pack_data: Dict[str, Any], generated_at_iso: str) -> str:
    """Compute sha256 over stable pack JSON + timestamp, hex digest."""
    payload = f"{_stable_serialize(pack_data)}|{generated_at_iso}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _write_csv(pack: Dict[str, Any], *, hash_hex: str, generated_at_iso: str) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)

    w.writerow(["Pack", pack.get("pack"), "Period", pack.get("period")])
    for section in pack.get("sections", []) or []:
        w.writerow([])
        w.writerow(["Section", section.get("id"), section.get("title")])
        for item in section.get("items", []) or []:
            label = item.get("label") or item.get("method") or "item"
            # Standard fields
            for key in ("value_cents", "window_start", "window_end", "method"):
                if key in item:
                    w.writerow(["Item", label, key, item.get(key)])
            # Rows, if present
            rows = item.get("rows")
            if isinstance(rows, list) and rows:
                # Derive a header from keys across rows (stable order)
                header_keys = sorted({k for r in rows if isinstance(r, dict) for k in r.keys()})
                w.writerow(["Rows"] + header_keys)
                for r in rows:
                    if isinstance(r, dict):
                        w.writerow([""] + [r.get(k) for k in header_keys])
    w.writerow([])
    w.writerow(["Hash", hash_hex])
    w.writerow(["Generated At", generated_at_iso])

    return buf.getvalue().encode("utf-8")


def _render_pdf_html(pack: Dict[str, Any], *, hash_hex: str, generated_at_iso: str) -> str:
    """Render a very simple HTML 'PDF' representation with footer hash.

    We intentionally keep this self-contained without external PDF libs per task notes.
    """
    def esc(s: Any) -> str:
        try:
            return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        except Exception:
            return str(s)

    parts: list[str] = []
    parts.append("<html><head><meta charset='utf-8'><title>Questionnaire Export</title>")
    parts.append(
        "<style>body{font-family:Arial,Helvetica,sans-serif;margin:24px}h1{margin:0 0 4px}h2{margin:18px 0 6px}table{border-collapse:collapse;width:100%}th,td{border:1px solid #ddd;padding:6px;text-align:left}tfoot{font-size:12px;color:#555;margin-top:16px} .muted{color:#777;font-size:12px}</style>"
    )
    parts.append("</head><body>")
    parts.append(f"<h1>Pack: {esc(pack.get('pack'))}</h1>")
    parts.append(f"<div class='muted'>Period: {esc(pack.get('period'))}</div>")

    for section in pack.get("sections", []) or []:
        parts.append(f"<h2>{esc(section.get('title') or section.get('id'))}</h2>")
        for item in section.get("items", []) or []:
            label = item.get("label") or item.get("method") or "item"
            parts.append(f"<div><strong>{esc(label)}</strong></div>")
            parts.append("<table>")
            parts.append("<tbody>")
            for key in ("value_cents", "window_start", "window_end", "method"):
                if key in item:
                    parts.append(f"<tr><th>{esc(key)}</th><td>{esc(item.get(key))}</td></tr>")
            parts.append("</tbody></table>")
            rows = item.get("rows")
            if isinstance(rows, list) and rows:
                header_keys = sorted({k for r in rows if isinstance(r, dict) for k in r.keys()})
                parts.append("<table><thead><tr>")
                for k in header_keys:
                    parts.append(f"<th>{esc(k)}</th>")
                parts.append("</tr></thead><tbody>")
                for r in rows:
                    if isinstance(r, dict):
                        parts.append("<tr>")
                        for k in header_keys:
                            parts.append(f"<td>{esc(r.get(k))}</td>")
                        parts.append("</tr>")
                parts.append("</tbody></table>")
    parts.append("<hr>")
    parts.append(f"<div class='muted'>Hash: {esc(hash_hex)}</div>")
    parts.append(f"<div class='muted'>Generated At: {esc(generated_at_iso)}</div>")
    parts.append("</body></html>")
    return "".join(parts)


@dataclass
class ExportRequest:
    pack: str
    period: Optional[str] = None
    format: str = "csv"  # csv | pdf | both
    include_pii: bool = False
    include_memos: bool = False


@router.post("/api/q/export")
def export_pack(req: ExportRequest):  # type: ignore[valid-type]
    # Validate format
    fmt = (req.format or "csv").strip().lower()
    if fmt not in ("csv", "pdf", "both"):
        raise HTTPException(status_code=400, detail="format must be one of: csv, pdf, both")

    # Assemble pack
    pack = assemble_pack(req.pack, req.period)
    if pack.get("error"):
        raise HTTPException(status_code=404, detail=f"Unknown pack: {req.pack}")

    # Redact and compute hash on stable representation
    redacted = redact_pack(pack, include_pii=bool(req.include_pii), include_memos=bool(req.include_memos))
    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    hash_hex = compute_export_hash(redacted, ts)

    # Ensure export dir
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    base = f"{pack.get('pack')}_{pack.get('period')}_{ts.replace(':','').replace('-','')}"

    resp: Dict[str, Any] = {
        "pack": pack.get("pack"),
        "period": pack.get("period"),
        "hash": hash_hex,
        "generated_at": ts,
    }

    if fmt in ("csv", "both"):
        csv_bytes = _write_csv(redacted, hash_hex=hash_hex, generated_at_iso=ts)
        csv_path = EXPORT_DIR / f"{base}.csv"
        with open(csv_path, "wb") as f:
            f.write(csv_bytes)
        resp["csv_url"] = f"/exports/{csv_path.name}"

    if fmt in ("pdf", "both"):
        html = _render_pdf_html(redacted, hash_hex=hash_hex, generated_at_iso=ts)
        pdf_path = EXPORT_DIR / f"{base}.pdf.html"
        with open(pdf_path, "w", encoding="utf-8") as f:
            f.write(html)
        resp["pdf_url"] = f"/exports/{pdf_path.name}"

    return resp

