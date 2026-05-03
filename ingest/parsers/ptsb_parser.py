"""
Stub parser for Permanent TSB (PTSB) CSV exports.

PTSB CSV columns (typical — varies by export format):
    "Date","Description","Debit","Credit","Balance"

Source: PTSB 365 online banking → Download transactions → CSV.
Debit = money out (negative), Credit = money in (positive).
Some PTSB exports may use "Amount" with sign convention.
"""

from __future__ import annotations

from typing import Any, Dict, List, Set

BANK_LABEL = "Permanent TSB"

# PTSB CSV header signatures (lower-cased, stripped)
# Two common variants:
#   Variant A: Date, Description, Debit, Credit, Balance
#   Variant B: Date, Description, Amount, Balance
_VARIANT_A: Set[str] = {"date", "description", "debit", "credit", "balance"}
_VARIANT_B: Set[str] = {"date", "description", "amount", "balance"}


def can_parse(headers: List[str]) -> bool:
    """Return True if *headers* looks like a PTSB CSV header row.

    Accepts either Variant A (separate debit/credit) or
    Variant B (single amount column).
    """
    normalised = {h.strip().lower() for h in headers}
    return _VARIANT_A.issubset(normalised) or _VARIANT_B.issubset(normalised)


def parse_row(row: Dict[str, str]) -> Dict[str, Any]:
    """Normalise one PTSB CSV row into the canonical field set.

    Handles both Variant A (separate debit/credit columns) and
    Variant B (single amount column with sign convention).

    Returns
    -------
    dict with keys: date, payee, memo, amount_cents, currency, category
    """
    # ---- TODO: implement actual field mapping ----
    def _parse(raw: str) -> int:
        cleaned = raw.replace(",", "").strip()
        if not cleaned:
            return 0
        try:
            return int(round(float(cleaned) * 100))
        except (ValueError, TypeError):
            return 0

    # Try Variant A first (separate debit/credit)
    debit_raw = row.get("Debit", row.get("debit", ""))
    credit_raw = row.get("Credit", row.get("credit", ""))
    if debit_raw or credit_raw:
        debit = _parse(debit_raw)
        credit = _parse(credit_raw)
        amount_cents = credit - debit
    else:
        # Variant B (single amount — negative is debit)
        amount_cents = _parse(row.get("Amount", row.get("amount", "0")))

    return {
        "date": row.get("Date", "").strip(),
        "payee": row.get("Description", "").strip(),
        "memo": "",
        "amount_cents": amount_cents,
        "currency": "EUR",
        "category": "",
    }
