"""Security helpers for the Flask application."""
from __future__ import annotations

from datetime import datetime, timedelta
from threading import Lock
from typing import Optional, Tuple

from flask import current_app, request


class LoginRateLimiter:
    """Simple in-memory rate limiter for login attempts."""

    def __init__(
        self,
        *,
        max_attempts: int = 5,
        window: timedelta = timedelta(seconds=60),
        block: timedelta = timedelta(minutes=5),
    ) -> None:
        self.max_attempts = max_attempts
        self.window = window
        self.block = block
        self._entries: dict[str, dict[str, Optional[datetime] | int]] = {}
        self._lock = Lock()

    def _get_entry(self, key: str, now: datetime) -> dict[str, Optional[datetime] | int]:
        entry = self._entries.get(key)
        if entry is None:
            entry = {
                "count": 0,
                "reset_at": now + self.window,
                "blocked_until": None,
            }
            self._entries[key] = entry
            return entry

        blocked_until = entry.get("blocked_until")
        if isinstance(blocked_until, datetime) and blocked_until <= now:
            # Block expired → reset counters
            entry["blocked_until"] = None
            entry["count"] = 0
            entry["reset_at"] = now + self.window

        reset_at = entry.get("reset_at")
        if isinstance(reset_at, datetime) and reset_at <= now:
            entry["count"] = 0
            entry["reset_at"] = now + self.window
        return entry

    def is_blocked(self, key: str) -> Tuple[bool, Optional[datetime]]:
        now = datetime.utcnow()
        with self._lock:
            entry = self._entries.get(key)
            if not entry:
                return False, None
            blocked_until = entry.get("blocked_until")
            if isinstance(blocked_until, datetime) and blocked_until > now:
                return True, blocked_until
            if isinstance(blocked_until, datetime) and blocked_until <= now:
                # Block expired → reset entry
                entry["blocked_until"] = None
                entry["count"] = 0
                entry["reset_at"] = now + self.window
            reset_at = entry.get("reset_at")
            if isinstance(reset_at, datetime) and reset_at <= now:
                entry["count"] = 0
                entry["reset_at"] = now + self.window
            return False, None

    def register_failure(self, key: str) -> Tuple[bool, Optional[datetime]]:
        now = datetime.utcnow()
        with self._lock:
            entry = self._get_entry(key, now)
            blocked_until = entry.get("blocked_until")
            if isinstance(blocked_until, datetime) and blocked_until > now:
                return True, blocked_until

            entry["count"] = int(entry.get("count", 0)) + 1
            if entry["count"] >= self.max_attempts:
                blocked_until = now + self.block
                entry["blocked_until"] = blocked_until
                entry["count"] = 0
                entry["reset_at"] = blocked_until + self.window
                return True, blocked_until

            self._entries[key] = entry
            return False, entry.get("blocked_until") if isinstance(entry.get("blocked_until"), datetime) else None

    def reset(self, key: str) -> None:
        with self._lock:
            self._entries.pop(key, None)

    def remaining_attempts(self, key: str) -> int:
        now = datetime.utcnow()
        with self._lock:
            entry = self._entries.get(key)
            if not entry:
                return self.max_attempts
            blocked_until = entry.get("blocked_until")
            if isinstance(blocked_until, datetime) and blocked_until > now:
                return 0
            reset_at = entry.get("reset_at")
            if isinstance(reset_at, datetime) and reset_at <= now:
                return self.max_attempts
            return max(self.max_attempts - int(entry.get("count", 0)), 0)


def client_identifier() -> str:
    """Return a best-effort identifier for the current client (IP address)."""
    forwarded_for = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if forwarded_for:
        return forwarded_for
    return request.remote_addr or "unknown"


def retry_after_seconds(until: Optional[datetime]) -> int:
    if not until:
        return 0
    return max(int((until - datetime.utcnow()).total_seconds()), 0)


def init_security(app) -> LoginRateLimiter:
    """Initialise security helpers on the Flask application."""
    limiter = LoginRateLimiter(
        max_attempts=app.config.get("LOGIN_RATE_LIMIT_ATTEMPTS", 5),
        window=timedelta(seconds=app.config.get("LOGIN_RATE_LIMIT_WINDOW", 60)),
        block=timedelta(seconds=app.config.get("LOGIN_RATE_LIMIT_BLOCK", 300)),
    )
    app.extensions["login_rate_limiter"] = limiter

    csp = app.config.get("CONTENT_SECURITY_POLICY")
    if isinstance(csp, str):
        csp = " ".join(segment for segment in csp.splitlines() if segment).strip() or None
    hsts = app.config.get("STRICT_TRANSPORT_SECURITY")

    @app.after_request
    def _apply_security_headers(response):  # type: ignore[override]
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        if csp:
            response.headers.setdefault("Content-Security-Policy", csp)
        if hsts and request.is_secure:
            response.headers.setdefault("Strict-Transport-Security", hsts)
        return response

    return limiter


def current_login_rate_limiter() -> LoginRateLimiter:
    app = current_app._get_current_object()
    limiter = app.extensions.get("login_rate_limiter")
    if not isinstance(limiter, LoginRateLimiter):
        limiter = init_security(app)
    return limiter
