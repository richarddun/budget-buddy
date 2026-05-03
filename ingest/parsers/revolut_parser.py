"""
Stub parser for Revolut bank CSV exports.

Revolut CSV columns (typical):
    Type, Product, Started Date, Completed Date, Description, Amount,
    Fee, Currency, State, Balance

Reference: https://help.revolut.com/help/manage-account/statements-and-reports/how-can-i-download-an-statement-of-my-revolut-account/
"""

from __future__ import annotations

from typing import Any, Dict, List

BANK_LABEL = "Revolut"

# Canonical Revolut CSV header signatures (lower-cased, stripped)
_SIGNATURE_HEADERS = {
    "type",
    "product",
    "started date",
    "completed date",
    "description",
    "amount",
    "fee",
    "currency",
    "state",
    "balance",
}


def can_parse(headers: List[str]) -> bool:
    """Return True if *headers* looks like a Revolut CSV header row.

    Checks that all signature fields appear in the given header list
    (case-insensitive).
    """
    normalised = {h.strip().lower() for h in headers}
    return _SIGNATURE_HEADERS.issubset(normalised)


def parse_row(row: Dict[str, str]) -> Dict[str, Any]:
    """Normalise one Revolut CSV row into the canonical field set.

    Returns
    -------
    dict with keys: date, payee, memo, amount, currency, category
    """
    # ---- TODO: implement actual field mapping ----
    # The following is a structural skeleton that preserves raw data
    # while producing the expected output shape.
    raw_amount = row.get("Amount", "0").replace(",", "").strip()
    try:
        amount_cents = int(round(float(raw_amount) * 100))
    except (ValueError, TypeError):
        amount_cents = 0

    return {
        "date": row.get("Completed Date", row.get("Started Date", "")).strip(),
        "payee": row.get("Description", "").strip(),
        "memo": f'Type: {row.get("Type", "")} | State: {row.get("State", "")}',
        "amount_cents": amount_cents,
        "currency": row.get("Currency", "EUR").strip(),
        "category": "",  # unmapped — csv_importer will use Holding
    }
