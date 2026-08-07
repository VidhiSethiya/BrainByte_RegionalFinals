"""Abstract interface every ticket source implements: JiraSource for the real
board, SyntheticSource for the offline fallback. `TICKET_SOURCE` in config.py
picks one; nothing upstream (the poller, the API routes, the triage graph) codes
to a specific source — only to this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class TicketSource(ABC):
    """One ticket-tracking backend.

    Every raw ticket dict returned by `fetch_since` carries the same shape,
    regardless of source: `external_id`, `title`, `body`, `application`,
    `environment`, `channel`, `reporter`, `attachments`, `raw` (source-specific
    extras), `updated_at` (ISO 8601 — the watermark field).

    Write methods are single best-effort calls. Retry/backoff is the adapter's
    own concern (JiraSource has it); the caller is responsible for deciding
    *whether* to write at all — see ai/tools.py::ticket_update, the one place
    that decision is actually enforced.
    """

    name: str = "unknown"

    @abstractmethod
    def fetch_since(self, watermark: str | None, limit: int = 50) -> list[dict[str, Any]]:
        """Tickets updated since `watermark` (ISO 8601, or None for everything),
        oldest first, capped at `limit`."""

    @abstractmethod
    def update(self, external_id: str, fields: dict[str, Any]) -> None:
        """Write triage fields back. Keys: severity, priority_score,
        assigned_team, confidence — the adapter maps these onto whatever the
        underlying system calls them."""

    @abstractmethod
    def add_comment(self, external_id: str, text: str) -> None:
        """Post the rationale + citations as a plain-text comment."""

    @abstractmethod
    def transition(self, external_id: str, status: str) -> None:
        """Move the ticket's workflow state. `status` is one of TicketSphere's
        own statuses; a source with no matching workflow state should no-op
        rather than raise."""
