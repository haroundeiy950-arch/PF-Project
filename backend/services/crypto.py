"""Encryption helpers for sensitive data such as face embeddings."""

from __future__ import annotations

import base64
import hashlib
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken # type: ignore

from backend.config import settings


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_bytes(data: bytes) -> bytes:
    return _fernet().encrypt(data)


def decrypt_bytes(token: Optional[bytes]) -> Optional[bytes]:
    if not token:
        return None
    try:
        return _fernet().decrypt(token)
    except (InvalidToken, ValueError):
        return None
