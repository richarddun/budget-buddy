from __future__ import annotations

import logging
import os
from typing import Iterable


SENSITIVE_ENV_VARS: Iterable[str] = (
    "YNAB_TOKEN",
    "OAI_KEY",
    "ADMIN_TOKEN",
    "CSRF_TOKEN",
)


class RedactSecretsFilter(logging.Filter):
    """Logging filter that redacts known secret values appearing in log messages."""

    def __init__(self, name: str = "") -> None:
        super().__init__(name)
        # Snapshot env values to redact
        self._secrets = [str(os.getenv(k) or "") for k in SENSITIVE_ENV_VARS]
        # Also redact plausible token-like strings configured via *_TOKEN vars
        for k, v in os.environ.items():
            if k.endswith("_TOKEN") and v and v not in self._secrets:
                self._secrets.append(str(v))

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            # IMPORTANT: Using record.getMessage() formats msg % args.
            # If we then mutate record.msg only and leave record.args intact,
            # the logging framework will attempt to re-format and raise a TypeError.
            # Strategy: redact on the fully formatted message and then clear args.
            formatted = str(record.getMessage())
            redacted = formatted
            for s in self._secrets:
                if s:
                    redacted = redacted.replace(s, "***")
            # Replace message with redacted text and clear args to avoid re-formatting
            record.msg = redacted
            record.args = ()
        except Exception:
            # Best effort: never break logging
            pass
        return True
