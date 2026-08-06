"""Append-only, hash-chained audit log.

Each entry hashes its own content together with the previous entry's hash, so any
retroactive edit or deletion breaks the chain and `verify_chain()` reports the first
bad row. That is the difference between a log and an audit log.

Never UPDATE or DELETE rows in this table.
"""

from __future__ import annotations

import hashlib
import json
import threading

from db.sqlite.models import AuditLog, SessionLocal
from observability.telemetry import log

_lock = threading.Lock()

GENESIS = "0" * 64


def _entry_hash(prev_hash: str, user_id: str | None, action: str, resource: str | None,
                details: dict, timestamp: str) -> str:
    payload = json.dumps(
        {
            "prev": prev_hash,
            "user_id": user_id,
            "action": action,
            "resource": resource,
            "details": details,
            "ts": timestamp,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def record(
    action: str,
    user_id: str | None = None,
    resource: str | None = None,
    **details,
) -> str:
    """Append one entry. Never raises — an audit failure must not fail the request,
    but it must be loud."""
    try:
        with _lock, SessionLocal() as s:
            last = s.query(AuditLog).order_by(AuditLog.id.desc()).first()
            prev_hash = last.entry_hash if last else GENESIS

            entry = AuditLog(
                user_id=user_id,
                action=action,
                resource=resource,
                details=details,
                prev_hash=prev_hash,
            )
            # created_at is server-default, so stamp it here to hash the real value.
            from db.sqlite.models import _now

            entry.created_at = _now()
            entry.entry_hash = _entry_hash(
                prev_hash, user_id, action, resource, details, entry.created_at.isoformat()
            )
            s.add(entry)
            s.commit()
            return entry.entry_hash
    except Exception as exc:  # noqa: BLE001
        log.error("AUDIT WRITE FAILED action=%s: %s", action, exc)
        return ""


def verify_chain() -> dict:
    """Walk the chain and report the first tampered row, if any."""
    with SessionLocal() as s:
        entries = s.query(AuditLog).order_by(AuditLog.id.asc()).all()

    prev_hash = GENESIS
    for entry in entries:
        expected = _entry_hash(
            prev_hash,
            entry.user_id,
            entry.action,
            entry.resource,
            entry.details or {},
            entry.created_at.isoformat(),
        )
        if expected != entry.entry_hash or entry.prev_hash != prev_hash:
            return {"valid": False, "entries": len(entries), "broken_at": entry.id}
        prev_hash = entry.entry_hash

    return {"valid": True, "entries": len(entries), "broken_at": None}
