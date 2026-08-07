"""Background poller: every `JIRA_POLL_SECONDS` (or on demand via
`POST /api/integrations/sync`), ask the configured TicketSource what changed
since the last watermark, and run each ticket through
`ai.agents.ingest_and_triage()`.

Runs in a daemon thread started once from run.py. The Flask dev server here is
single-process, so a plain thread + timer loop is the right amount of
infrastructure for a 24-hour build — a real deployment would move this to a queue
consumer, per `.claude/plans/BLUEPRINT.md` §12.
"""

from __future__ import annotations

import threading
from typing import Any

from config import settings
from observability.telemetry import log

# A synthetic system identity for tickets the poller ingests with nobody logged
# in to attribute them to. Carries "all" clearances so index_ticket()'s ACL
# stamping and ingest_and_triage()'s retrieval calls are never blocked by the
# poller's own identity — the ticket's *team* ACL (acl_<team>) still applies to
# every other user reading it afterwards; this only affects who the audit log
# credits with the ingest itself.
_SYSTEM_USER = {"id": "system:poller", "username": "system:poller", "role": "admin", "clearances": ["all"]}

_watermark: str | None = None
_watermark_source: str | None = None  # which source _watermark was loaded/saved for
_lock = threading.Lock()
_stop = threading.Event()


def _load_watermark(source_name: str) -> str | None:
    """Read the persisted watermark for this source. None if never polled."""
    from db.sqlite.models import SessionLocal, SyncState

    try:
        with SessionLocal() as s:
            row = s.get(SyncState, source_name)
            return row.watermark if row else None
    except Exception as exc:  # noqa: BLE001 - a fresh DB with no table yet must not crash the poll
        log.warning("poll: could not load persisted watermark for %s: %s", source_name, exc)
        return None


def _save_watermark(source_name: str, watermark: str | None) -> None:
    """Upsert the watermark so a restart resumes here instead of re-fetching
    (and re-triaging — real LLM cost) the whole board from the beginning."""
    from db.sqlite.models import SessionLocal, SyncState

    try:
        with SessionLocal() as s:
            row = s.get(SyncState, source_name)
            if row is None:
                row = SyncState(source=source_name)
                s.add(row)
            row.watermark = watermark
            s.commit()
    except Exception as exc:  # noqa: BLE001 - persistence failing must not break the poll batch
        log.warning("poll: could not persist watermark for %s: %s", source_name, exc)


def _dead_letter_row(raw: dict[str, Any], source_name: str, exc: BaseException) -> None:
    """If a TicketRow already exists for this external_id, mark failed and bump
    sync_attempts. Used when ingest_and_triage raises before it can dead-letter."""
    external_id = str(raw.get("external_id") or "").strip()
    if not external_id:
        return
    ticket_source = str(raw.get("source") or source_name or "").strip() or source_name
    try:
        from db.sqlite.models import SessionLocal
        from db.sqlite.models import Ticket as TicketRow

        with SessionLocal() as s:
            row = (
                s.query(TicketRow)
                .filter_by(source=ticket_source, external_id=external_id)
                .first()
            )
            if row is None:
                return
            row.status = "failed"
            row.last_error = str(exc)[:500] or "ingest_and_triage raised"
            row.sync_attempts = (row.sync_attempts or 0) + 1
            s.commit()
    except Exception as db_exc:  # noqa: BLE001 - dead-letter must not break the poll batch
        log.error("poll: dead-letter update failed for %s: %s", external_id, db_exc)


def poll_once() -> dict[str, Any]:
    """Fetch everything new since the last watermark and triage it. Safe to call
    concurrently with the background loop — the lock serialises actual polls so
    a manual POST /integrations/sync and the timer never race and never
    double-advance the watermark."""
    from ai.agents import ingest_and_triage
    from ai.tools import get_ticket_source

    global _watermark, _watermark_source
    with _lock:
        try:
            source = get_ticket_source()
        except Exception as exc:  # noqa: BLE001 - e.g. TICKET_SOURCE=jira with no credentials
            log.error("poll: could not resolve ticket source: %s", exc)
            return {"pulled": 0, "triaged": 0, "failed": 0, "error": str(exc)}

        # Load the persisted watermark on this process's first poll of this
        # source (or if the configured source changed). Every poll after that
        # uses the in-memory value — no DB read on the hot path — and every
        # poll ends by writing it back, so a restart resumes correctly instead
        # of re-fetching (and re-triaging) the whole board again.
        if _watermark_source != source.name:
            _watermark = _load_watermark(source.name)
            _watermark_source = source.name
            log.info("poll: resumed watermark for source=%s: %s", source.name, _watermark)

        try:
            raw_tickets = source.fetch_since(_watermark, limit=50)
        except Exception as exc:  # noqa: BLE001
            log.error("poll: fetch_since failed: %s", exc)
            return {"pulled": 0, "triaged": 0, "failed": 0, "error": str(exc)}

        triaged = 0
        failed = 0
        latest_watermark = _watermark
        for raw in raw_tickets:
            try:
                row, _state = ingest_and_triage(raw, _SYSTEM_USER)
                if row.status == "failed":
                    failed += 1
                else:
                    triaged += 1
            except Exception as exc:  # noqa: BLE001 - one bad ticket must not stop the batch
                failed += 1
                log.error("poll: ingest_and_triage failed for %s: %s",
                           raw.get("external_id"), exc)
                _dead_letter_row(raw, source.name, exc)

            updated = raw.get("updated_at") or ""
            if updated and (latest_watermark is None or updated > latest_watermark):
                latest_watermark = updated

        _watermark = latest_watermark or _watermark
        _save_watermark(source.name, _watermark)
        log.info(
            "poll: source=%s pulled=%d triaged=%d failed=%d watermark=%s",
            source.name, len(raw_tickets), triaged, failed, _watermark,
        )
        return {"pulled": len(raw_tickets), "triaged": triaged, "failed": failed, "error": None}


def _loop() -> None:
    while not _stop.is_set():
        try:
            poll_once()
        except Exception as exc:  # noqa: BLE001 - the loop must survive one bad cycle
            log.error("poller loop error: %s", exc)
        _stop.wait(settings.JIRA_POLL_SECONDS)


_thread: threading.Thread | None = None


def start_background_poller() -> None:
    """Called once from run.py::create_app(). No-op if already running — safe to
    call again after stop_background_poller()."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="ticket-poller", daemon=True)
    _thread.start()
    log.info(
        "ticket poller started (source=%s, every %ds)",
        settings.TICKET_SOURCE, settings.JIRA_POLL_SECONDS,
    )


def stop_background_poller() -> None:
    _stop.set()


def get_watermark() -> str | None:
    """Current watermark for the configured source. Lazily resumes from the
    persisted value if this process hasn't polled yet, so a status check
    right after boot shows the true resumed position, not a misleading
    None."""
    global _watermark, _watermark_source
    if _watermark_source is None:
        try:
            from ai.tools import get_ticket_source

            name = get_ticket_source().name
        except Exception:  # noqa: BLE001 - e.g. no credentials configured yet
            return _watermark
        _watermark = _load_watermark(name)
        _watermark_source = name
    return _watermark
