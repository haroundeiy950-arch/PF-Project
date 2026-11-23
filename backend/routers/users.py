"""User and role management (Section 13)."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request # type: ignore
from sqlalchemy import func, select # type: ignore
from sqlalchemy.orm import Session # type: ignore

from backend.constants import PERMISSIONS, ROLE_DEFINITIONS
from backend.database import get_db
from backend.deps import client_ip, get_current_user, require_permissions
from backend.models import AuditLog, Role, User
from backend.schemas import UserCreate, UserUpdate
from backend.security import hash_password
from backend.serializers import role_payload, user_payload
from backend.services.audit import record_audit
from backend.utils.time_utils import now

router = APIRouter(prefix="/api", tags=["Users & roles"])


def _active_admin_count(db: Session, exclude_id: int | None = None) -> int:
    query = (
        select(func.count())
        .select_from(User)
        .join(Role, User.role_id == Role.id)
        .where(Role.name == "admin", User.is_active.is_(True))
    )
    if exclude_id:
        query = query.where(User.id != exclude_id)
    return db.scalar(query) or 0


@router.get("/roles")
def list_roles(
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions("manage_users")),
):
    roles = db.scalars(select(Role).order_by(Role.id)).all()
    return {"items": [role_payload(role) for role in roles], "permissions": PERMISSIONS}


@router.get("/roles/matrix")
def permission_matrix(_: User = Depends(require_permissions("manage_users"))):
    return {
        "permissions": PERMISSIONS,
        "roles": [
            {
                "name": name,
                "label": str(definition["label"]),
                "permissions": list(definition["permissions"]),
            }
            for name, definition in ROLE_DEFINITIONS.items()
        ],
    }


@router.get("/users")
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions("manage_users")),
):
    users = db.scalars(select(User).order_by(User.id)).all()
    return {"items": [user_payload(user) for user in users], "total": len(users)}


@router.post("/users", status_code=201)
def create_user(
    payload: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("manage_users")),
):
    username = payload.username.strip().lower()
    if db.scalar(select(User).where(User.username == username)):
        raise HTTPException(status_code=409, detail="That username already exists")
    role = db.scalar(select(Role).where(Role.name == payload.role))
    if role is None:
        raise HTTPException(status_code=400, detail="Unknown role")

    user = User(
        username=username,
        full_name=payload.full_name,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role_id=role.id,
        is_active=payload.is_active,
    )
    db.add(user)
    record_audit(
        db,
        actor,
        "user.create",
        target=username,
        detail=f"Role: {role.name}",
        ip_address=client_ip(request),
        commit=False,
    )
    db.commit()
    db.refresh(user)
    return user_payload(user)


@router.patch("/users/{user_id}")
def update_user(
    user_id: int,
    payload: UserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("manage_users")),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if payload.role is not None and payload.role != user.role.name:
        role = db.scalar(select(Role).where(Role.name == payload.role))
        if role is None:
            raise HTTPException(status_code=400, detail="Unknown role")
        if user.role.name == "admin" and role.name != "admin" and _active_admin_count(db, user.id) == 0:
            raise HTTPException(status_code=400, detail="At least one active administrator is required")
        user.role_id = role.id

    if payload.is_active is False and user.role.name == "admin" and _active_admin_count(db, user.id) == 0:
        raise HTTPException(status_code=400, detail="At least one active administrator is required")
    if payload.is_active is False and user.id == actor.id:
        raise HTTPException(status_code=400, detail="You cannot disable your own account")

    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.email is not None:
        user.email = payload.email
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.password:
        user.password_hash = hash_password(payload.password)

    record_audit(
        db,
        actor,
        "user.update",
        target=user.username,
        detail="Profile updated" + (" · password reset" if payload.password else ""),
        ip_address=client_ip(request),
        commit=False,
    )
    db.commit()
    db.refresh(user)
    return user_payload(user)


@router.delete("/users/{user_id}")
def deactivate_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("manage_users")),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == actor.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    if user.role.name == "admin" and _active_admin_count(db, user.id) == 0:
        raise HTTPException(status_code=400, detail="At least one active administrator is required")

    # Soft delete keeps the audit trail and acknowledgement history intact.
    user.is_active = False
    record_audit(
        db,
        actor,
        "user.deactivate",
        target=user.username,
        detail="Account disabled (history retained)",
        ip_address=client_ip(request),
        commit=False,
    )
    db.commit()
    return {"message": f"{user.username} has been disabled"}


@router.get("/audit-logs")
def audit_logs(
    limit: int = 100,
    offset: int = 0,
    action: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions("view_audit")),
):
    from backend.serializers import audit_payload

    limit = max(1, min(limit, 500))
    query = select(AuditLog).order_by(AuditLog.created_at.desc())
    count_query = select(func.count()).select_from(AuditLog)
    if action:
        query = query.where(AuditLog.action == action)
        count_query = count_query.where(AuditLog.action == action)
    total = db.scalar(count_query) or 0
    rows = db.scalars(query.offset(offset).limit(limit)).all()
    return {"items": [audit_payload(row) for row in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/audit-logs/actions")
def audit_actions(
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions("view_audit")),
):
    rows = db.execute(select(AuditLog.action, func.count()).group_by(AuditLog.action)).all()
    return {"items": [{"action": action, "count": count} for action, count in rows]}
