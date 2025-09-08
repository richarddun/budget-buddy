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

    def _redact_text(self, text: str) -> str:
        redacted = text
        for s in self._secrets:
            if s:
                redacted = redacted.replace(s, "***")
        return redacted

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            # If there are args (e.g., uvicorn.access expects 5-tuple), redact them in-place
            # without clearing, to preserve formatter expectations.
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {
                        k: (self._redact_text(v) if isinstance(v, str) else v)
                        for k, v in record.args.items()
                    }
                elif isinstance(record.args, (list, tuple)):
                    seq = [self._redact_text(a) if isinstance(a, str) else a for a in record.args]
                    record.args = tuple(seq) if isinstance(record.args, tuple) else seq
                # Redact any secrets that might appear in the format string itself
                if isinstance(record.msg, str):
                    record.msg = self._redact_text(record.msg)
            else:
                # No args: safe to redact on the fully formatted string and clear args
                formatted = str(record.getMessage())
                record.msg = self._redact_text(formatted)
                record.args = ()
        except Exception:
            # Best effort: never break logging
            pass
        return True
