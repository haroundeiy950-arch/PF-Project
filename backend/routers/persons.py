"""Authorized people and face enrollment (privacy-first).

Consent is mandatory before a face embedding is calculated.  Embeddings are
never exposed through the API and are encrypted at rest with a key derived from
``SECRET_KEY``.  Face recognition only answers "known / unknown"; it can never
trigger a danger alarm by itself.
"""

from __future__ import annotations

import json
from typing import Optional

import cv2 # type: ignore
import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile # type: ignore
from sqlalchemy import func, or_, select # type: ignore
from sqlalchemy.orm import Session # type: ignore

from backend.ai.face import get_face_engine
from backend.config import settings
from backend.database import get_db
from backend.deps import client_ip, get_current_user, require_permissions
from backend.models import AuthorizedPerson, User
from backend.schemas import MessageResponse, PersonUpdate
from backend.serializers import person_payload
from backend.services import imaging, storage
from backend.services.audit import record_audit
from backend.services.crypto import encrypt_bytes
from backend.utils.time_utils import now

router = APIRouter(prefix="/api", tags=["People"])

MAX_PHOTO_BYTES = 8 * 1024 * 1024


def _get(db: Session, person_id: int) -> AuthorizedPerson:
    person = db.get(AuthorizedPerson, person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Person not found")
    return person


def _validate_photo(data: bytes) -> np.ndarray:
    if not data:
        raise HTTPException(status_code=400, detail="Photo file is empty")
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="Photo must be smaller than 8 MB")
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(status_code=400, detail="Unsupported image format (use JPG or PNG)")
    return image


def _embedding_status() -> dict:
    engine = get_face_engine()
    return {
        **engine.status,
        "enabled": settings.face_recognition_enabled,
        "threshold": settings.face_match_threshold,
        "note": (
            "Face recognition is disabled in the environment. Enable "
            "FACE_RECOGNITION_ENABLED and install requirements-ai.txt to match faces."
        )
        if not settings.face_recognition_enabled
        else "InsightFace is optional; the engine loads on first enrollment.",
    }


def _try_embedding(data: bytes, person: AuthorizedPerson) -> bool:
    if not settings.face_recognition_enabled:
        return False
    engine = get_face_engine()
    vector = engine.extract_embedding(data)
    if not vector:
        return False
    person.embedding_encrypted = encrypt_bytes(
        json.dumps([round(float(value), 6) for value in vector]).encode("utf-8")
    )
    return True


@router.get("/persons/meta")
def persons_meta(_: User = Depends(get_current_user)):
    return {
        "face_engine": _embedding_status(),
        "consent_notice": (
            "Face recognition requires the person's explicit written consent. "
            "Embeddings are encrypted at rest, never displayed and can be deleted "
            "at any time by revoking consent."
        ),
        "max_photo_mb": 8,
        "accepted_formats": ["image/jpeg", "image/png"],
    }


@router.get("/persons")
def list_persons(
    q: Optional[str] = None,
    active_only: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = select(AuthorizedPerson).order_by(AuthorizedPerson.full_name)
    if active_only:
        query = query.where(AuthorizedPerson.is_active.is_(True))
    if q:
        pattern = f"%{q.strip()}%"
        query = query.where(
            or_(
                AuthorizedPerson.full_name.ilike(pattern),
                AuthorizedPerson.title.ilike(pattern),
                AuthorizedPerson.notes.ilike(pattern),
            )
        )
    rows = db.scalars(query).all()
    return {
        "items": [person_payload(person) for person in rows],
        "total": len(rows),
        "consented": sum(1 for person in rows if person.consent_given),
        "with_embedding": sum(1 for person in rows if person.embedding_encrypted),
    }


@router.post("/persons", status_code=201)
async def create_person(
    request: Request,
    full_name: str = Form(..., min_length=2, max_length=120),
    title: str = Form(default="", max_length=120),
    notes: str = Form(default=""),
    consent_given: bool = Form(default=False),
    photo: Optional[UploadFile] = File(default=None),
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("manage_faces")),
):
    existing = db.scalar(
        select(AuthorizedPerson).where(func.lower(AuthorizedPerson.full_name) == full_name.strip().lower())
    )
    if existing:
        raise HTTPException(status_code=409, detail="A person with that name is already enrolled")

    person = AuthorizedPerson(
        full_name=full_name.strip(),
        title=title.strip(),
        consent_given=consent_given,
        consent_at=now() if consent_given else None,
        notes=notes.strip(),
        is_active=True,
    )
    db.add(person)
    db.flush()

    embedding_created = False
    if photo is not None and photo.filename:
        data = await photo.read()
        _validate_photo(data)
        person.photo_path = imaging.save_face_photo(data, person.id)
        if consent_given:
            embedding_created = _try_embedding(data, person)

    record_audit(
        db,
        actor,
        "person.enroll",
        target=person.full_name,
        detail=(
            f"consent={consent_given} · embedding={'yes' if embedding_created else 'no'}"
        ),
        ip_address=client_ip(request),
        commit=False,
    )
    db.commit()
    db.refresh(person)
    payload = person_payload(person)
    payload["embedding_created"] = embedding_created
    return payload


@router.get("/persons/{person_id}")
def get_person(
    person_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    person = _get(db, person_id)
    payload = person_payload(person)
    payload["consent_at"] = person.consent_at.isoformat() if person.consent_at else None
    payload["face_engine"] = _embedding_status()
    return payload


@router.patch("/persons/{person_id}")
def update_person(
    person_id: int,
    payload: PersonUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("manage_faces")),
):
    person = _get(db, person_id)
    data = payload.model_dump(exclude_unset=True)

    if "consent_given" in data:
        if data["consent_given"] and not person.consent_given:
            person.consent_at = now()
        if data["consent_given"] is False:
            person.consent_at = None
            person.embedding_encrypted = None
        person.consent_given = bool(data["consent_given"])
        data.pop("consent_given")

    for key, value in data.items():
        setattr(person, key, value)

    record_audit(
        db,
        actor,
        "person.update",
        target=person.full_name,
        detail=", ".join(sorted(data.keys())) or "Consent updated",
        ip_address=client_ip(request),
        commit=False,
    )
    db.commit()
    db.refresh(person)
    return person_payload(person)


@router.post("/persons/{person_id}/photo")
async def replace_photo(
    person_id: int,
    request: Request,
    photo: UploadFile = File(...),
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("manage_faces")),
):
    person = _get(db, person_id)
    data = await photo.read()
    _validate_photo(data)
    if person.photo_path:
        storage.delete_file(person.photo_path)
    person.photo_path = imaging.save_face_photo(data, person.id)
    embedded = _try_embedding(data, person) if person.consent_given else False
    record_audit(
        db,
        actor,
        "person.photo",
        target=person.full_name,
        detail=f"Photo replaced · embedding={'yes' if embedded else 'no'}",
        ip_address=client_ip(request),
        commit=False,
    )
    db.commit()
    db.refresh(person)
    payload = person_payload(person)
    payload["embedding_created"] = embedded
    return payload


@router.post("/persons/{person_id}/reenroll")
def reenroll_face(
    person_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("manage_faces")),
):
    """Recompute the embedding from the stored photo."""
    person = _get(db, person_id)
    if not person.consent_given:
        raise HTTPException(status_code=400, detail="Written consent is required before enrollment")
    if not person.photo_path:
        raise HTTPException(status_code=400, detail="Upload a photo first")
    try:
        data = storage.absolute_path(person.photo_path).read_bytes()
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Stored photo is unavailable: {exc}") from exc
    embedded = _try_embedding(data, person)
    record_audit(
        db,
        actor,
        "person.reenroll",
        target=person.full_name,
        detail="Embedding recomputed" if embedded else "Face engine unavailable",
        ip_address=client_ip(request),
        commit=False,
    )
    db.commit()
    return {
        "message": "Face enrollment updated" if embedded else "Photo stored; face engine unavailable",
        "has_embedding": embedded,
    }


@router.delete("/persons/{person_id}")
def delete_person(
    person_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("manage_faces")),
):
    person = _get(db, person_id)
    name = person.full_name
    if person.photo_path:
        storage.delete_file(person.photo_path)
    db.delete(person)
    record_audit(
        db,
        actor,
        "person.delete",
        target=name,
        detail="Enrollment and biometric data deleted",
        ip_address=client_ip(request),
        commit=False,
    )
    db.commit()
    return MessageResponse(message=f"{name} removed from the authorized list")


__all__ = ["router"]
