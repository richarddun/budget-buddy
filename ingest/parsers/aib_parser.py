"""
Parser for Allied Irish Banks (AIB) CSV exports.

AIB 365 Online CSV format (personal accounts):
    Date, Type, Details, Amount, Balance

Column descriptions:
    Date     — Transaction date (DD/MM/YYYY or DD-MM-YYYY)
    Type     — Transaction type (DEB, CREDIT, DIR DEBIT, STANDING ORDER, etc.)
    Details  — Merchant name / transaction description
    Amount   — Numeric value with sign: positive = credit (money in),
               negative = debit (money out).
    Balance  — Running balance after transaction (ignored by parser)

**Note:** Unlike some other banks (BOI, PTSB), AIB uses a single Amount
column with sign convention rather than separate Debit/Credit columns.

References:
    - AIB 365 Online: Download → Transactions → CSV
    - https://aib.ie/personal/help/online-banking

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

# ---- AIB CSV signature headers ----

# Format A: Date, Type, Details, Amount, Balance (most common AIB 365 online format)
_SIGNATURE_FORMAT_A = {
    "date",
    "type",
    "details",
    "amount",
    "balance",
}

# ---- Internal helpers ----


def _parse_date(raw: str) -> str:
    """Normalise an AIB date string to ISO format (YYYY-MM-DD).

    Handles: DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY, YYYY-MM-DD.
    Falls back to raw value if unparseable.
    """
    s = (raw or "").strip()
    if not s:
        return ""

    # Already ISO
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s

    # Try common Irish date formats
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except (ValueError, TypeError):
            continue

    # Last resort — return as-is
    return raw


def _parse_amount(raw: str) -> int:
    """Parse a decimal amount string to integer cents.

    Handles: "42.50" -> 4250, "-12.34" -> -1234, with commas.
    Returns 0 for empty/unparseable values.
    """
    s = (raw or "").strip()
    if not s:
        return 0
    # Remove currency symbols and whitespace
    s = s.replace("€", "").replace("$", "").replace("£", "").strip()
    # Remove thousands separator
    s = s.replace(",", "")
    try:
        return int(round(float(s) * 100))
    except (ValueError, TypeError):
        return 0


# ---- Public contract ----

def can_parse(headers: List[str]) -> bool:
    """Return True if *headers* looks like an AIB CSV header row.

    Accepts one format:
      Format A: Date, Type, Details, Amount, Balance (standard AIB 365 online)
    """
    normalised = {h.strip().lower() for h in headers}
    return _SIGNATURE_FORMAT_A.issubset(normalised)


def parse_row(row: Dict[str, str]) -> Dict[str, Any]:
    """Normalise one AIB CSV row into the canonical field set.

    The canonical output contains:
        date         — ISO date string (YYYY-MM-DD)
        payee        — Merchant name or transaction description
        memo         — Transaction metadata (type info)
        amount_cents — Signed integer in cents (positive = credit, negative = debit)
        currency     — Always "EUR"
        category     — Empty string (csv_importer assigns Holding)

    Parameters
    ----------
    row : dict
        Raw CSV row from DictReader. Keys are case-sensitive as in the
        actual CSV header (but we look up by lowercase alias too).

    Returns
    -------
    dict with canonical fields
    """
    # ---- Build a case-insensitive lookup ----
    r_lower = {k.strip().lower(): v for k, v in row.items()}

    # ---- Date ----
    raw_date = r_lower.get("date", "")
    date_iso = _parse_date(raw_date)

    # ---- Payee + Type info ----
    payee = (r_lower.get("details") or "").strip()
    type_info = (r_lower.get("type") or "").strip()

    # ---- Amount (cents, signed) ----
    # "Amount" column: positive = credit (inflow), negative = debit (outflow)
    amount_cents = _parse_amount(r_lower.get("amount", "0"))

    # ---- Memo — include transaction type as context ----
    memo = f"Type: {type_info}" if type_info else ""

    return {
        "date": date_iso,
        "payee": payee,
        "memo": memo,
        "amount_cents": amount_cents,
        "currency": "EUR",
        "category": "",
    }
