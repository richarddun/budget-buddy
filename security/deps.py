from __future__ import annotations

import os
import time
from typing import Dict, Tuple

from fastapi import HTTPException, Request


_RL_STORE: Dict[Tuple[str, str], Tuple[int, float]] = {}


def _admin_token() -> str | None:
    """Return admin token from env if configured."""
    tok = os.getenv("ADMIN_TOKEN")
    if tok:
        return str(tok)
    return None


def require_auth(request: Request) -> None:
    """Require a bearer token for writes if ADMIN_TOKEN is set.

    Accepts either:
    - Authorization: Bearer <token>
    - X-Admin-Token: <token>
    """
    tok = _admin_token()
    if not tok:
        return  # Not enforced when no token configured (dev/tests)

    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    via_header = None
    if auth and auth.lower().startswith("bearer "):
        via_header = auth.split(" ", 1)[1].strip()
    x_admin = request.headers.get("x-admin-token") or request.headers.get("X-Admin-Token")
    candidate = via_header or x_admin
    if candidate != tok:
        raise HTTPException(status_code=401, detail="Unauthorized")


def require_csrf(request: Request) -> None:
    """If CSRF_TOKEN env set, require header X-CSRF-Token to match.

    Keeps behavior consistent with api/key_events.py but centralized.
    """
    token = os.getenv("CSRF_TOKEN")
    if not token:
        return
    header = request.headers.get("x-csrf-token") or request.headers.get("X-CSRF-Token")
    if header != token:
        raise HTTPException(status_code=403, detail="Invalid or missing CSRF token")


def rate_limit(request: Request, *, scope: str, limit: int | None = None, window_s: int | None = None) -> None:
    """Very simple in-memory fixed-window rate limit per client IP and scope.

    Configure defaults via env ADMIN_RATE_LIMIT (e.g., "30/min" or "60/300s").
    """
    # Determine defaults
    if limit is None or window_s is None:
        rl_env = (os.getenv("ADMIN_RATE_LIMIT") or "30/min").strip().lower()
        try:
            parts = rl_env.split("/")
            n = int(parts[0])
            w = parts[1]
            if w.endswith("min"):
                window = 60
            elif w.endswith("s"):
                window = int(w[:-1])
            elif w.endswith("m"):
                window = int(w[:-1]) * 60
            else:
                # Fallback seconds
                window = int(w)
            limit = n if limit is None else limit
            window_s = window if window_s is None else window_s
        except Exception:
            limit = limit or 30
            window_s = window_s or 60

    assert limit is not None and window_s is not None

    ip = request.client.host if request.client else "unknown"
    key = (ip, scope)
    now = time.time()
    count, window_start = _RL_STORE.get(key, (0, now))
    if now - window_start >= window_s:
        # Reset window
        count = 0
        window_start = now
    count += 1
    _RL_STORE[key] = (count, window_start)
    if count > limit:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

