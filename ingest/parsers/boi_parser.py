"""
Stub parser for Bank of Ireland (BOI) CSV exports.

BOI CSV columns (typical):
    "Transaction Date","Description","Debit Amount","Credit Amount","Balance"

Source: BOI 365 online banking → Download → CSV format.
Debit = money out (negative), Credit = money in (positive).
"""

from __future__ import annotations

from typing import Any, Dict, List

BANK_LABEL = "Bank of Ireland"

# Canonical BOI CSV header signatures (lower-cased, stripped)
_SIGNATURE_HEADERS = {
    "transaction date",
    "description",
    "debit amount",
    "credit amount",
    "balance",
}


def can_parse(headers: List[str]) -> bool:
    """Return True if *headers* looks like a BOI CSV header row.

    Checks that all signature fields appear in the given header list
    (case-insensitive).
    """
    normalised = {h.strip().lower() for h in headers}
    return _SIGNATURE_HEADERS.issubset(normalised)


def parse_row(row: Dict[str, str]) -> Dict[str, Any]:
    """Normalise one BOI CSV row into the canonical field set.

    BOI has separate debit and credit columns.
    Debit = outflow (negative), Credit = inflow (positive).
    If both are present they should cancel — normally only one is non-empty.

    Returns
    -------
    dict with keys: date, payee, memo, amount_cents, currency, category
    """
    # ---- TODO: implement actual field mapping ----
    def _parse_amount(raw: str) -> int:
        cleaned = raw.replace(",", "").strip()
        if not cleaned or cleaned == "":
            return 0
        try:
            return int(round(float(cleaned) * 100))
        except (ValueError, TypeError):
            return 0

    debit = _parse_amount(row.get("Debit Amount", ""))
    credit = _parse_amount(row.get("Credit Amount", ""))
    amount_cents = credit - debit  # debit is positive in CSV so subtract

    return {
        "date": row.get("Transaction Date", "").strip(),
        "payee": row.get("Description", "").strip(),
        "memo": "",
        "amount_cents": amount_cents,
        "currency": "EUR",
        "category": "",
    }
