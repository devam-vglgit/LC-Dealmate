"""Single-account session auth for the portal.

Credentials live in backend/.env. Tokens are HMAC-signed and carry their own
expiry, so there's no server-side session table and a restart doesn't log
everyone out.

Scope: this guards a local/internal tool against casual access. It is a single
shared account with a plaintext password in .env — fine behind your own network,
not something to expose to the public internet.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

USERNAME = os.getenv("LC_AUTH_USERNAME", "").strip()
PASSWORD = os.getenv("LC_AUTH_PASSWORD", "").strip()

# A generated fallback means tokens simply don't survive a restart if the secret
# was never set — inconvenient, never insecure.
SECRET = os.getenv("LC_SESSION_SECRET", "").strip() or secrets.token_hex(32)

try:
    SESSION_SECONDS = int(float(os.getenv("LC_SESSION_HOURS", "12")) * 3600)
except ValueError:
    SESSION_SECONDS = 12 * 3600


def enabled() -> bool:
    """No credentials configured means the API stays open — so an existing
    deployment doesn't lock itself out the moment this module ships."""
    return bool(USERNAME and PASSWORD)


def check_credentials(username: str, password: str) -> bool:
    if not enabled():
        return False
    # compare_digest on both halves so a wrong username and a wrong password
    # take the same time to reject.
    user_ok = hmac.compare_digest((username or "").strip(), USERNAME)
    pass_ok = hmac.compare_digest(password or "", PASSWORD)
    return user_ok and pass_ok


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _sign(body: str) -> str:
    return _b64(hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).digest())


def issue_token(username: str) -> str:
    payload = {"u": username, "exp": int(time.time()) + SESSION_SECONDS}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    return f"{body}.{_sign(body)}"


def verify_token(token: str | None) -> bool:
    if not token:
        return False
    try:
        body, signature = token.split(".", 1)
    except ValueError:
        return False
    if not hmac.compare_digest(signature, _sign(body)):
        return False
    try:
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except Exception:
        return False
    return float(payload.get("exp", 0)) > time.time()


def token_from_header(header: str | None) -> str | None:
    if not header:
        return None
    prefix = "bearer "
    return header[len(prefix):].strip() if header.lower().startswith(prefix) else header.strip()
