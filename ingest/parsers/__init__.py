"""
Bank parser plugin registry for csv_importer.

Each parser module exposes:
    BANK_LABEL: str           — human-readable bank name
    can_parse(headers: list[str]) -> bool   — detect if headers match this bank's CSV format
    parse_row(row: dict[str, str]) -> dict  — normalise one CSV row into canonical fields

Discovery & dispatch:
    registered_parsers()             — returns list of all parser modules
    detect_parser(headers)           — returns first parser whose can_parse() returns True
    parse_known_rows(parser, rows)   — runs parse_row across all rows with the matched parser
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Any, Dict, List, Optional


def registered_parsers() -> list:
    """Discover and return all parser modules under ingest/parsers/.

    Skips __init__ itself.
    """
    parsers = []
    package_path = __path__  # type: ignore  # set by Python for packages
    for finder, name, is_pkg in pkgutil.iter_modules(package_path):
        if name == "__init__":
            continue
        mod = importlib.import_module(f"ingest.parsers.{name}")
        if all(hasattr(mod, attr) for attr in ("BANK_LABEL", "can_parse", "parse_row")):
            parsers.append(mod)
    return parsers


def detect_parser(headers: List[str]) -> Optional[Any]:
    """Return the first parser that recognises the given CSV headers.

    Iterates over registered parsers in discovery order and returns the
    first one whose ``can_parse(headers)`` returns ``True``.
    Returns ``None`` if no parser matches.
    """
    for parser in registered_parsers():
        try:
            if parser.can_parse(headers):
                return parser
        except Exception:
            continue
    return None


def parse_known_rows(parser: Any, rows: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """Run ``parse_row`` across every row using the matched parser.

    Each result dict contains at minimum::

        {
            "date":       "2025-01-15",
            "payee":      "Centra",
            "memo":       "Weekly shopping",
            "amount":     "42.50",
            "currency":   "EUR",
            "category":   "Groceries",
        }

    Rows that raise during parsing are collected with an ``_error`` key.
    """
    results: List[Dict[str, Any]] = []
    for i, row in enumerate(rows):
        try:
            result = parser.parse_row(row)
            if isinstance(result, dict):
                results.append(result)
        except Exception as exc:
            results.append({"_row_index": i, "_error": str(exc)})
    return results


__all__ = ["registered_parsers", "detect_parser", "parse_known_rows"]
