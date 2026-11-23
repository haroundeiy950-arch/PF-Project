"""Password hashing, JWT issuing/validation and permission helpers.

Implemented with the Python standard library (``hashlib`` + ``hmac``) so the
security layer has no fragile third-party dependency while remaining
industry-standard for this project (PBKDF2-HMAC-SHA256, HS256 tokens).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from backend.config import settings
from backend.constants import ROLE_DEFINITIONS

_PBKDF2_ITERATIONS = settings.password_iterations
_ALGO = "pbkdf2_sha256"


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    """Hash a password with a random salt."""
    if not password or len(password) < 6:
        raise ValueError("Password must contain at least 6 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"{_ALGO}${_PBKDF2_ITERATIONS}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time password verification."""
    try:
        algo, iterations, salt_b64, digest_b64 = stored.split("$", 3)
        if algo != _ALGO:
            return False
        salt = _b64decode(salt_b64)
        expected = _b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(iterations)
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# JWT (HS256)
# ---------------------------------------------------------------------------
def _sign(message: str) -> str:
    signature = hmac.new(
        settings.secret_key.encode("utf-8"), message.encode("ascii"), hashlib.sha256
    ).digest()
    return _b64encode(signature)


def create_access_token(
    user_id: int,
    username: str,
    role: str,
    permissions: Iterable[str],
    full_name: str = "",
    expires_minutes: Optional[int] = None,
) -> str:
    issued = datetime.now(timezone.utc)
    expires = issued + timedelta(
        minutes=expires_minutes or settings.access_token_expire_minutes
    )
    header = {"alg": settings.algorithm, "typ": "JWT"}
    payload = {
        "sub": str(user_id),
        "username": username,
        "full_name": full_name,
        "role": role,
        "permissions": list(permissions),
        "iat": int(issued.timestamp()),
        "exp": int(expires.timestamp()),
    }
    segments = [
        _b64encode(json.dumps(header, separators=(",", ":")).encode("utf-8")),
        _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
    ]
    signing_input = ".".join(segments)
    return f"{signing_input}.{_sign(signing_input)}"


def decode_token(token: str) -> Dict[str, Any]:
    """Validate a token and return its payload.  Raises ``ValueError``."""
    try:
        header_b64, payload_b64, signature = token.split(".")
    except ValueError as exc:
        raise ValueError("Malformed token") from exc

    signing_input = f"{header_b64}.{payload_b64}"
    expected = _sign(signing_input)
    if not hmac.compare_digest(expected, signature):
        raise ValueError("Invalid token signature")

    header = json.loads(_b64decode(header_b64))
    if header.get("alg") != settings.algorithm:
        raise ValueError("Unsupported token algorithm")

    payload = json.loads(_b64decode(payload_b64))
    if int(payload.get("exp", 0)) < int(datetime.now(timezone.utc).timestamp()):
        raise ValueError("Token has expired")
    return payload


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------
def permissions_for_role(role_name: str) -> List[str]:
    definition = ROLE_DEFINITIONS.get(role_name)
    return list(definition["permissions"]) if definition else []


def has_permission(permissions: Iterable[str], required: str) -> bool:
    permissions = list(permissions)
    return required in permissions or "*" in permissions
