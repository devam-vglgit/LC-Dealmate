"""Session auth for the portal, plus a CMS embed handoff.

DealMate's own login (shared username/password) remains for local use.
When CMS opens DealMate it mints a short-lived HS256 JWT with
``CMS_EMBED_SECRET`` and passes it as ``?token=``. Same secret on both sides.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any

USERNAME = os.getenv("LC_AUTH_USERNAME", "").strip()
PASSWORD = os.getenv("LC_AUTH_PASSWORD", "").strip()
# Prefer a dedicated embed secret. CMS can also inject its existing SSO_JWT_SECRET.
CMS_EMBED_SECRET = (
    os.getenv("CMS_EMBED_SECRET", "").strip()
    or os.getenv("SSO_JWT_SECRET", "").strip()
)

SECRET = (
    os.getenv("LC_SESSION_SECRET", "").strip()
    or os.getenv("SESSION_SECRET", "").strip()
    or secrets.token_hex(32)
)

try:
    SESSION_SECONDS = int(float(os.getenv("LC_SESSION_HOURS", "12")) * 3600)
except ValueError:
    SESSION_SECONDS = 12 * 3600


def enabled() -> bool:
    """Auth is on when DealMate has its own login *or* CMS can hand off a JWT."""
    return bool((USERNAME and PASSWORD) or CMS_EMBED_SECRET)


def password_login_enabled() -> bool:
    return bool(USERNAME and PASSWORD)


def cms_handoff_enabled() -> bool:
    return bool(CMS_EMBED_SECRET)


def check_credentials(username: str, password: str) -> bool:
    if not password_login_enabled():
        return False
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


def _b64url_decode(segment: str) -> bytes:
    pad = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + pad)


def _verify_cms_jwt(token: str) -> dict[str, Any] | None:
    """HS256 JWT issued by CMS. Payload must include ``exp``; ``sub`` is the user."""
    if not CMS_EMBED_SECRET:
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    header_b64, payload_b64, sig_b64 = parts
    signing = f"{header_b64}.{payload_b64}".encode()
    expected = hmac.new(CMS_EMBED_SECRET.encode(), signing, hashlib.sha256).digest()
    try:
        given = _b64url_decode(sig_b64)
    except Exception:
        return None
    if not hmac.compare_digest(given, expected):
        return None
    try:
        header = json.loads(_b64url_decode(header_b64))
        payload = json.loads(_b64url_decode(payload_b64))
    except Exception:
        return None
    if str(header.get("alg") or "").upper() != "HS256":
        return None
    now = time.time()
    if float(payload.get("nbf", 0) or 0) > now + 30:
        return None
    if float(payload.get("exp", 0) or 0) <= now:
        return None
    return payload


def verify_token(token: str | None) -> bool:
    if not token:
        return False
    if CMS_EMBED_SECRET and _verify_cms_jwt(token):
        return True
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


def exchange_cms_token(cms_jwt: str) -> str | None:
    """Turn a CMS JWT into a DealMate session token so the rest of the API is unchanged."""
    payload = _verify_cms_jwt(cms_jwt)
    if not payload:
        return None
    user = str(
        payload.get("sub")
        or payload.get("u")
        or payload.get("username")
        or payload.get("id")
        or "cms"
    )
    return issue_token(user)


def token_from_header(header: str | None) -> str | None:
    if not header:
        return None
    prefix = "bearer "
    return header[len(prefix):].strip() if header.lower().startswith(prefix) else header.strip()
