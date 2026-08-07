"""Offline ticket source — reads db/vectordb/data/seed/tickets/*.json, the same
corpus `seed_vector_db.py --generate` produces. Writes are logged, not sent
anywhere; there is nothing external to send them to.

This is the default (`TICKET_SOURCE=synthetic`) and the safety net if Jira access
falls through on the day — the whole pipeline (ingest -> triage -> approve ->
"sync") runs identically against this source, just without a real system on the
other end of the write.
"""

from __future__ import annotations

import json
from typing import Any

from config import settings
from integrations.ticket_source import TicketSource
from observability.telemetry import log


class SyntheticSource(TicketSource):
    name = "synthetic"

    @property
    def _dir(self):
        return settings.SEED_DIR / "tickets"

    def fetch_since(self, watermark: str | None, limit: int = 50) -> list[dict[str, Any]]:
        directory = self._dir
        if not directory.is_dir():
            log.warning(
                "synthetic ticket dir %s does not exist yet (run "
                "seed_vector_db.py --generate first) — nothing to fetch",
                directory,
            )
            return []

        rows: list[dict[str, Any]] = []
        for path in sorted(directory.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                log.warning("skipping unreadable ticket file %s: %s", path, exc)
                continue
            updated = str(data.get("updated_at") or data.get("created_at") or "")
            if watermark and updated and updated <= watermark:
                continue
            rows.append(_normalize(data))

        rows.sort(key=lambda r: r.get("updated_at") or "")
        return rows[:limit]

    def update(self, external_id: str, fields: dict[str, Any]) -> None:
        log.info("synthetic.update %s <- %s (no-op — no external system to write to)",
                  external_id, fields)

    def add_comment(self, external_id: str, text: str) -> None:
        log.info("synthetic.add_comment %s: %s", external_id, text[:120].replace("\n", " "))

    def transition(self, external_id: str, status: str) -> None:
        log.info("synthetic.transition %s -> %s (no-op)", external_id, status)


def _normalize(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "external_id": str(data.get("external_id") or data.get("id") or ""),
        "source": "synthetic",
        "title": str(data.get("title") or ""),
        "body": str(data.get("body") or data.get("description") or ""),
        "application": str(data.get("application") or ""),
        "environment": str(data.get("environment") or "prod"),
        "channel": str(data.get("channel") or "synthetic"),
        "reporter": str(data.get("reporter") or ""),
        "assignee": str(data.get("assignee") or ""),
        "attachments": list(data.get("attachments") or []),
        "raw": data,
        "updated_at": str(data.get("updated_at") or data.get("created_at") or ""),
    }
