"""FastAPI dependencies: authentication, permissions and request metadata."""

from __future__ import annotations

from typing import Callable, Iterable, Optional

from fastapi import Depends, HTTPException, Request, status # type: ignore
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer # type: ignore
from sqlalchemy import select # type: ignore
from sqlalchemy.orm import Session # type: ignore

from backend.database import get_db
from backend.models import User
from backend.security import decode_token, has_permission

bearer_scheme = HTTPBearer(auto_error=False)


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def user_from_token(db: Session, token: str) -> Optional[User]:
    try:
        payload = decode_token(token)
    except ValueError:
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    user = db.get(User, int(user_id))
    if user is None or not user.is_active:
        return None
    return user


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = user_from_token(db, credentials.credentials)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Optional[User]:
    if credentials is None:
        return None
    return user_from_token(db, credentials.credentials)


def get_stream_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """Streams are opened by <img>/<video> tags, so accept ?token= as well."""
    token = request.query_params.get("token") or ""
    if not token:
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            token = header[7:]
    user = user_from_token(db, token) if token else None
    if user is None:
        raise HTTPException(status_code=401, detail="Stream authentication required")
    return user


def require_permissions(*required: str) -> Callable:
    """Dependency factory enforcing one or more permissions."""

    def dependency(user: User = Depends(get_current_user)) -> User:
        permissions = user.role.permissions if user.role else []
        missing = [permission for permission in required if not has_permission(permissions, permission)]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {', '.join(missing)}",
            )
        return user

    return dependency


def require_any_permission(*required: str) -> Callable:
    def dependency(user: User = Depends(get_current_user)) -> User:
        permissions = user.role.permissions if user.role else []
        if not any(has_permission(permissions, permission) for permission in required):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this resource",
            )
        return user

    return dependency


def user_permissions(user: User) -> Iterable[str]:
    return list(user.role.permissions) if user.role else []


__all__ = [
    "bearer_scheme",
    "client_ip",
    "get_current_user",
    "get_optional_user",
    "get_stream_user",
    "get_db",
    "require_permissions",
    "require_any_permission",
    "user_permissions",
    "user_from_token",
]
