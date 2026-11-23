"""Audit and repair the on-disk evidence archive.

Every recording row, referenced snapshot/clip and media folder is checked.  An
in-progress continuous segment is treated as expected: it is still being written
and has not been archived into the database yet.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List, Set

import cv2  # type: ignore
from sqlalchemy import select  # type: ignore
from sqlalchemy.orm import Session  # type: ignore

from backend.config import settings
from backend.models import AuthorizedPerson, Event, Incident, Recording
from backend.services.storage import absolute_path, delete_file
from backend.utils.logging import get_logger

log = get_logger("evidence_audit")

ACTIVE_WINDOW_SECONDS = 180
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
VIDEO_SUFFIXES = {".mp4", ".avi", ".mov", ".mkv"}


def _is_active(path: Path) -> bool:
    try:
        return time.time() - path.stat().st_mtime <= ACTIVE_WINDOW_SECONDS
    except OSError:  # pragma: no cover - filesystem dependent
        return False


def _validate(relative: str) -> Dict:
    path = absolute_path(relative)
    if not path.is_file():
        return {"exists": False, "valid": False, "size": 0, "reason": "missing"}
    size = path.stat().st_size
    if size == 0:
        return {"exists": True, "valid": False, "size": 0, "reason": "empty"}
    try:
        suffix = path.suffix.lower()
        if suffix in IMAGE_SUFFIXES:
            valid = cv2.imread(str(path)) is not None
            reason = "ok" if valid else "undecodable image"
        elif suffix in VIDEO_SUFFIXES:
            capture = cv2.VideoCapture(str(path))
            ok, frame = capture.read()
            capture.release()
            valid = bool(ok and frame is not None)
            reason = "ok" if valid else "undecodable video"
        else:
            valid, reason = True, "unrecognized extension"
    except Exception as exc:  # pragma: no cover - hardware dependent
        valid, reason = False, f"validation error: {exc}"
    return {"exists": True, "valid": valid, "size": size, "reason": reason}


def _add_reference(references: Dict[str, List[str]], path: str, source: str) -> None:
    if path:
        references.setdefault(path, []).append(source)


def _collect_references(db: Session) -> Dict[str, List[str]]:
    references: Dict[str, List[str]] = {}
    for row in db.scalars(select(Recording)).all():
        _add_reference(references, row.path, f"recording:{row.id}")
    for row in db.scalars(select(Event)).all():
        _add_reference(references, row.snapshot_path, f"event:{row.id}")
    for row in db.scalars(select(Incident)).all():
        _add_reference(references, row.snapshot_path, f"incident:{row.id}:snapshot")
        _add_reference(references, row.clip_path, f"incident:{row.id}:clip")
    for row in db.scalars(select(AuthorizedPerson)).all():
        _add_reference(references, row.photo_path, f"person:{row.id}:photo")
    return references


def _clear_incident_reference(db: Session, relative: str) -> None:
    for incident in db.scalars(select(Incident)).all():
        changed = False
        if incident.snapshot_path == relative:
            incident.snapshot_path = ""
            changed = True
        if incident.clip_path == relative:
            incident.clip_path = ""
            changed = True
        if changed:
            log.info("Cleared missing evidence reference on incident %s", incident.id)


def _relative(path: Path) -> str:
    return str(path.relative_to(settings.storage_dir)).replace("\\", "/")


def audit_evidence(db: Session, repair: bool = False) -> Dict:
    """Check every evidence file and optionally repair invalid/orphaned ones."""
    references = _collect_references(db)
    issues: List[Dict] = []
    fixed: List[Dict] = []
    checked = 0

    recordings = db.scalars(select(Recording).order_by(Recording.id)).all()
    for recording in recordings:
        checked += 1
        info = _validate(recording.path)
        path = absolute_path(recording.path)
        active = info["exists"] and _is_active(path)
        problem = None
        if not info["exists"]:
            problem = "missing file"
        elif not info["valid"] and not active:
            problem = info["reason"]
        elif info["size"] != recording.size_bytes and not active:
            problem = f"size mismatch (database={recording.size_bytes}, disk={info['size']})"

        if problem is None:
            continue

        issue = {
            "kind": "recording",
            "path": recording.path,
            "sources": [f"recording:{recording.id}"],
            "problem": problem,
            "active": active,
            "expected": active,
        }
        issues.append(issue)

        if not repair or active:
            continue

        if info["exists"] and not info["valid"]:
            delete_file(recording.path)
        if problem.startswith("size mismatch"):
            recording.size_bytes = info["size"]
        else:
            _clear_incident_reference(db, recording.path)
            db.delete(recording)
        issue["fixed"] = True
        fixed.append(issue)

    for relative, sources in sorted(references.items()):
        if any(source.startswith("recording:") for source in sources):
            continue
        checked += 1
        info = _validate(relative)
        active = info["exists"] and _is_active(absolute_path(relative))
        if info["exists"] and (info["valid"] or active):
            continue
        problem = "missing file" if not info["exists"] else info["reason"]
        issues.append({
            "kind": "referenced_media",
            "path": relative,
            "sources": sources,
            "problem": problem,
            "active": active,
            "expected": active,
        })

    referenced_paths: Set[Path] = {absolute_path(path).resolve() for path in references}
    for directory in (settings.snapshots_dir, settings.clips_dir, settings.faces_dir):
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.resolve() in referenced_paths:
                continue
            checked += 1
            active = _is_active(path)
            relative = _relative(path)
            issue = {
                "kind": "orphan",
                "path": relative,
                "sources": [],
                "problem": "file not referenced by any archive row",
                "active": active,
                "expected": active,
            }
            issues.append(issue)
            if repair and not active:
                delete_file(relative)
                issue["fixed"] = True
                fixed.append(issue)

    if repair:
        db.flush()
    unresolved = [issue for issue in issues if not issue.get("expected") and not issue.get("fixed")]
    return {
        "healthy": not unresolved,
        "repair": bool(repair),
        "checked_files": checked,
        "summary": {
            "recording_rows": len(recordings),
            "referenced_files": len(references),
            "issues": len(issues),
            "expected_active": sum(1 for issue in issues if issue.get("expected")),
            "fixed": len(fixed),
            "unresolved": len(unresolved),
        },
        "issues": issues,
        "fixed": fixed,
    }


__all__ = ["audit_evidence"]
