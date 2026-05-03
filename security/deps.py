from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Dict, Tuple

from fastapi import HTTPException, Request


_RL_STORE: Dict[Tuple[str, str], Tuple[int, float]] = {}


# ── Session helpers ──────────────────────────────────────────────────────

_SESSION_COOKIE = "budget_buddy_session"
_SESSION_MAX_AGE = 3600 * 24 * 30  # 30 days (for remember-me)
_SESSION_MAX_AGE_DEFAULT = 3600 * 8  # 8 hours (default non-remember)


def _session_secret() -> str | None:
    """Return the HMAC signing secret derived from APP_ACCESS_PIN."""
    pin = os.getenv("APP_ACCESS_PIN")
    if not pin:
        return None
    # Derive a stable secret from the pin so we don't need a separate secret
    return hashlib.sha256(pin.encode()).hexdigest()


def _sign_session(value: str, secret: str) -> str:
    """Sign a session value with HMAC-SHA256."""
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def _make_session_cookie(secret: str, max_age: int) -> str:
    """Build signed session cookie value."""
    expiry = str(int(time.time()) + max_age)
    payload = f"authenticated|{expiry}"
    sig = _sign_session(payload, secret)
    return f"{payload}|{sig}"


def _verify_session_cookie(value: str, secret: str) -> bool:
    """Verify a signed session cookie value and check expiry."""
    try:
        parts = value.split("|")
        if len(parts) != 3:
            return False
        status, expiry_str, sig = parts
        if status != "authenticated":
            return False
        # Verify signature
        payload = f"{status}|{expiry_str}"
        expected = _sign_session(payload, secret)
        if not hmac.compare_digest(expected, sig):
            return False
        # Check expiry
        if int(expiry_str) < time.time():
            return False
        return True
    except (ValueError, IndexError):
        return False


def _is_lan_request(request: Request) -> bool:
    """Check if the request originates from a private LAN IP range.

    Returns True for:
      - 192.168.x.x
      - 10.x.x.x
      - 172.16-31.x.x
      - 127.x.x.x (localhost)
    """
    host = request.client.host if request.client else None
    if not host:
        return False
    # Check for private IPv4 ranges
    if host.startswith("192.168."):
        return True
    if host.startswith("10."):
        return True
    if host.startswith("127."):
        return True
    if host.startswith("172."):
        try:
            second = int(host.split(".")[1])
            if 16 <= second <= 31:
                return True
        except (ValueError, IndexError):
            pass
    # Also treat proxied requests with X-Forwarded-For as LAN-respectful
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first_ip = forwarded.split(",")[0].strip()
        if first_ip.startswith(("192.168.", "10.", "127.")):
            return True
        if first_ip.startswith("172."):
            try:
                second = int(first_ip.split(".")[1])
                if 16 <= second <= 31:
                    return True
            except (ValueError, IndexError):
                pass
    return False


def is_session_valid(request: Request) -> bool:
    """Check if the request has a valid session cookie."""
    secret = _session_secret()
    if not secret:
        # No PIN configured — no auth required (dev mode)
        return True
    # Auto-bypass PIN for LAN requests (PIN-less access)
    # DISABLED for now — require PIN everywhere
    # if _is_lan_request(request):
    #     return True
    cookie = request.cookies.get(_SESSION_COOKIE)
    if not cookie:
        return False
    return _verify_session_cookie(cookie, secret)


def require_session(request: Request) -> None:
    """Redirect to /login if no valid session cookie."""
    if not is_session_valid(request):
        base = str(request.base_url).rstrip("/")
        raise HTTPException(status_code=303, detail="Login required", headers={"Location": base + "/login"})


def get_session_max_age(remember: bool) -> int:
    """Return session max age based on remember-me flag."""
    if remember:
        return _SESSION_MAX_AGE
    return _SESSION_MAX_AGE_DEFAULT


def build_session_cookie(remember: bool) -> tuple[str, str, int]:
    """Build a session cookie value, name, and max-age.
    Returns (name, value, max_age)."""
    secret = _session_secret()
    if not secret:
        raise RuntimeError("APP_ACCESS_PIN not configured")
    max_age = get_session_max_age(remember)
    value = _make_session_cookie(secret, max_age)
    return (_SESSION_COOKIE, value, max_age)


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

