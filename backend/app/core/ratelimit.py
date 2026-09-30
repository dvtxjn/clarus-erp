"""
Login throttling (launch Phase 9):
  - at most 20 login attempts a minute per (IP address, email) — the office shares one IP and
    several people may sign in with the same ID at once (client, 2026-09-30) -> 429
  - 10 wrong passwords for one email within 15 minutes locks that email
    for 15 minutes, whatever the IP                                     -> 429
A successful login clears the email's failures. In memory (one app instance); a restart
resets it, which only ever makes it more lenient.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

PER_MINUTE = 20
LOCK_AFTER = 10
LOCK_WINDOW = 15 * 60
LOCK_FOR = 15 * 60

_lock = threading.Lock()
_attempts: dict[tuple[str, str], deque] = defaultdict(deque)
_failures: dict[str, deque] = defaultdict(deque)
_locked_until: dict[str, float] = {}


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")  # behind Render's proxy
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")


def check(request: Request, email: str) -> None:
    now, email = time.time(), (email or "").strip().lower()
    with _lock:
        if _locked_until.get(email, 0) > now:
            mins = int((_locked_until[email] - now) // 60) + 1
            raise HTTPException(status_code=429, detail=f"Too many wrong passwords — this account is locked for {mins} more minute(s).")
        q = _attempts[(client_ip(request), email)]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= PER_MINUTE:
            raise HTTPException(status_code=429, detail="Too many login attempts — wait a minute and try again.")
        q.append(now)


def failed(email: str) -> None:
    now, email = time.time(), (email or "").strip().lower()
    with _lock:
        f = _failures[email]
        while f and now - f[0] > LOCK_WINDOW:
            f.popleft()
        f.append(now)
        if len(f) >= LOCK_AFTER:
            _locked_until[email] = now + LOCK_FOR
            f.clear()


def succeeded(email: str) -> None:
    with _lock:
        _failures.pop((email or "").strip().lower(), None)


def reset() -> None:
    """Tests."""
    with _lock:
        _attempts.clear()
        _failures.clear()
        _locked_until.clear()
