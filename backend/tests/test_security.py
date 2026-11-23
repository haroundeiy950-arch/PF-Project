"""Tests for password hashing, JWT handling and the permission helpers."""

from __future__ import annotations

import time

import pytest # type: ignore

from backend.security import (
    create_access_token,
    decode_token,
    hash_password,
    has_permission,
    permissions_for_role,
    verify_password,
)


def test_password_hash_roundtrip():
    stored = hash_password("correct horse battery")
    assert stored.startswith("pbkdf2_sha256$")
    assert verify_password("correct horse battery", stored)
    assert not verify_password("wrong password", stored)
    assert not verify_password("", stored)


def test_password_hashes_use_unique_salts():
    first = hash_password("same-password")
    second = hash_password("same-password")
    assert first != second
    assert verify_password("same-password", first)
    assert verify_password("same-password", second)


def test_hash_password_rejects_short_passwords():
    with pytest.raises(ValueError):
        hash_password("123")


def test_malformed_hash_fails_closed():
    assert not verify_password("anything", "not-a-real-hash")
    assert not verify_password("anything", "md5$1$abc$def")


def test_token_roundtrip_contains_claims():
    token = create_access_token(7, "operator", "operator", ["view_live"], "Layla Nasser")
    payload = decode_token(token)
    assert payload["sub"] == "7"
    assert payload["username"] == "operator"
    assert payload["role"] == "operator"
    assert payload["permissions"] == ["view_live"]
    assert payload["full_name"] == "Layla Nasser"
    assert payload["exp"] > payload["iat"]


def test_tampered_token_is_rejected():
    token = create_access_token(1, "admin", "admin", ["*"])
    header, payload, signature = token.split(".")
    tampered = f"{header}.{payload}.{signature[::-1]}"
    with pytest.raises(ValueError):
        decode_token(tampered)
    with pytest.raises(ValueError):
        decode_token("only-one-segment")


def test_expired_token_is_rejected():
    token = create_access_token(1, "admin", "admin", ["*"], expires_minutes=-1)
    # exp is in the past already, but sleep briefly for clock granularity.
    time.sleep(0.01)
    with pytest.raises(ValueError, match="expired"):
        decode_token(token)


def test_permission_matrix():
    admin = permissions_for_role("admin")
    operator = permissions_for_role("operator")
    viewer = permissions_for_role("viewer")
    assert "manage_users" in admin and "manage_settings" in admin
    assert "acknowledge_alarms" in operator and "manage_users" not in operator
    assert viewer == ["view_live", "view_recordings"]
    assert has_permission(admin, "manage_users")
    assert has_permission(["*"], "anything")
    assert not has_permission(viewer, "manage_cameras")
    assert permissions_for_role("missing-role") == []
