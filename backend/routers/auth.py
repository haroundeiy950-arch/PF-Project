"""Authentication routes: login, current user, logout, password change."""

from __future__ import annotations

import threading
import time
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request, status # type: ignore
from sqlalchemy import select # type: ignore
from sqlalchemy.orm import Session # type: ignore

from backend.config import settings
from backend.database import get_db
from backend.deps import client_ip, get_current_user
from backend.models import User
from backend.schemas import LoginRequest, MessageResponse, TokenResponse
from backend.security import create_access_token, hash_password, verify_password
from backend.serializers import user_payload
from backend.services.audit import record_audit
from backend.utils.time_utils import now

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

_attempts: Dict[str, List[float]] = {}
_attempts_lock = threading.Lock()
MAX_ATTEMPTS = 8
WINDOW_SECONDS = 300


def _too_many_attempts(username: str) -> bool:
    with _attempts_lock:
        window = [stamp for stamp in _attempts.get(username, []) if time.time() - stamp < WINDOW_SECONDS]
        _attempts[username] = window
        return len(window) >= MAX_ATTEMPTS


def _record_attempt(username: str) -> None:
    with _attempts_lock:
        _attempts.setdefault(username, []).append(time.time())


def _clear_attempts(username: str) -> None:
    with _attempts_lock:
        _attempts.pop(username, None)


def build_token_response(user: User) -> TokenResponse:
    permissions = list(user.role.permissions or [])
    token = create_access_token(
        user_id=user.id,
        username=user.username,
        role=user.role.name,
        permissions=permissions,
        full_name=user.full_name,
    )
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
        user=user,
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    username = payload.username.strip().lower()
    if _too_many_attempts(username):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed attempts. Try again in a few minutes.",
        )

    user = db.scalar(select(User).where(User.username == username))
    if user is None or not verify_password(payload.password, user.password_hash):
        _record_attempt(username)
        record_audit(
            db,
            user,
            "auth.failed",
            target=username,
            detail="Invalid credentials",
            ip_address=client_ip(request),
        )
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account is disabled")

    _clear_attempts(username)
    user.last_login_at = now()
    record_audit(
        db,
        user,
        "auth.login",
        target=user.username,
        detail=f"Role: {user.role.name}",
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(user)
    return build_token_response(user)


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    payload = user_payload(user)
    payload["permissions"] = list(user.role.permissions or [])
    return payload


@router.post("/logout", response_model=MessageResponse)
def logout(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record_audit(
        db,
        user,
        "auth.logout",
        target=user.username,
        detail="Session closed",
        ip_address=client_ip(request),
    )
    return MessageResponse(message="Signed out")


@router.post("/change-password", response_model=MessageResponse)
def change_password(
    payload: dict,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    current = str(payload.get("current_password", ""))
    new = str(payload.get("new_password", ""))
    if not verify_password(current, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(new) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
    user.password_hash = hash_password(new)
    record_audit(
        db,
        user,
        "auth.change_password",
        target=user.username,
        detail="Password changed",
        ip_address=client_ip(request),
    )
    db.commit()
    return MessageResponse(message="Password updated")
