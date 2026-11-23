"""Audit logging service — every sensitive operation is recorded."""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session # type: ignore

from backend.models import AuditLog, User


def record_audit(
    db: Session,
    user: Optional[User],
    action: str,
    target: str = "",
    detail: str = "",
    ip_address: str = "",
    commit: bool = True,
) -> AuditLog:
    entry = AuditLog(
        user_id=user.id if user else None,
        action=action,
        target=target,
        detail=detail,
        ip_address=ip_address,
    )
    db.add(entry)
    if commit:
        db.commit()
        db.refresh(entry)
    return entry
