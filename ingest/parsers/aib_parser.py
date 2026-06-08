"""
Parser for Allied Irish Banks (AIB) CSV exports.

Supports two AIB export formats:

  Format A (AIB 365 Online standard):
      Date, Type, Details, Amount, Balance

  Format B (AIB Internet Banking — current account transaction export):
      Posted Account, Posted Transactions Date, Description1, Description2,
      Description3, Debit Amount, Credit Amount, Balance, Posted Currency,
      Transaction Type, Local Currency Amount, Local Currency

Each parser module must expose:
    BANK_LABEL: str
    can_parse(headers: list[str]) -> bool
    parse_row(row: dict[str, str]) -> dict
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List

BANK_LABEL = "AIB (Allied Irish Banks)"

# ---- CSV header signatures ----

# Format A: Date, Type, Details, Amount, Balance (standard AIB 365 online)
_SIG_A = {
    "date",
    "type",
    "details",
    "amount",
    "balance",
}

# Format B: Posted Transactions Date, Description1, Debit Amount, Credit Amount, Balance
# (AIB current-account transaction export with separate debit/credit columns)
_SIG_B = {
    "posted transactions date",
    "description1",
    "debit amount",
    "credit amount",
    "balance",
}


# ---- Internal helpers ----

def _parse_date(raw: str) -> str:
    """Normalise an AIB date string to ISO format (YYYY-MM-DD)."""
    s = (raw or "").strip().strip('"')
    if not s:
        return ""
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except (ValueError, TypeError):
            continue
    return raw


def _parse_amount(raw: str) -> int:
    """Parse a decimal amount string to integer cents."""
    s = (raw or "").strip().strip('"').replace(",", "")
    if not s:
        return 0
    s = s.replace("€", "").replace("$", "").replace("£", "").strip()
    try:
        return int(round(float(s) * 100))
    except (ValueError, TypeError):
        return 0


def _parse_amount_signed(raw: str) -> int:
    """Parse a possibly-negative amount string.

    Handles: "-42.50" → -4250, "42.50" → 4250.
    """
    s = (raw or "").strip().strip('"')
    if not s:
        return 0
    neg = s.startswith("-")
    s2 = s.replace(",", "").replace("€", "").replace("$", "").replace("£", "").strip().lstrip("-").strip()
    try:
        val = int(round(float(s2) * 100))
        return -val if neg else val
    except (ValueError, TypeError):
        return 0


# ---- Public contract ----

def can_parse(headers: List[str]) -> bool:
    """Return True if *headers* looks like an AIB CSV header row."""
    normalised = {h.strip().lower() for h in headers}
    return _SIG_A.issubset(normalised) or _SIG_B.issubset(normalised)


def parse_row(row: Dict[str, str]) -> Dict[str, Any]:
    """Normalise one AIB CSV row into canonical fields.

    Canonical output:
        date         — ISO date (YYYY-MM-DD)
        payee        — Merchant / description
        memo         — Extra context (transaction type, desc2/desc3)
        amount_cents — Signed integer cents; positive=credit, negative=debit
        currency     — Always "EUR"
        category     — Empty string
    """
    r = {k.strip().lower(): v for k, v in row.items()}

    # Detect which format we're dealing with
    is_format_b = "posted transactions date" in r

    if is_format_b:
        # ---- Format B: newer AIB export with separate debit/credit ----
        date_iso = _parse_date(r.get("posted transactions date", ""))
        payee = (r.get("description1") or "").strip().strip('"')

        # Build memo from desc2 + desc3 + transaction type
        memo_parts = []
        d2 = (r.get("description2") or "").strip().strip('"')
        d3 = (r.get("description3") or "").strip().strip('"')
        ttype = (r.get("transaction type") or "").strip()
        if d2:
            memo_parts.append(d2)
        if d3:
            memo_parts.append(d3)
        memo = " · ".join(memo_parts) if memo_parts else ""

        # Debit = money out (negative), Credit = money in (positive)
        debit_cents = _parse_amount(r.get("debit amount", "0"))
        credit_cents = _parse_amount(r.get("credit amount", "0"))
        amount_cents = credit_cents - debit_cents

        # Append transaction type to memo if we have it
        if ttype:
            memo = f"[{ttype}] {memo}".strip() if memo else ttype

        return {
            "date": date_iso,
            "payee": payee,
            "memo": memo,
            "amount_cents": amount_cents,
            "currency": "EUR",
            "category": "",
        }

    else:
        # ---- Format A: classic AIB 365 Online ----
        date_iso = _parse_date(r.get("date", ""))
        payee = (r.get("details") or "").strip()
        type_info = (r.get("type") or "").strip()
        amount_cents = _parse_amount_signed(r.get("amount", "0"))
        memo = f"[{type_info}]" if type_info else ""

        return {
            "date": date_iso,
            "payee": payee,
            "memo": memo,
            "amount_cents": amount_cents,
            "currency": "EUR",
            "category": "",
        }
